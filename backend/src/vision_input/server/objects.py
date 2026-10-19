"""물체 등록·관리 API.

좌표는 모두 0..1 정규화 (브라우저 미리보기 해상도와 처리 해상도가 다르므로).
등록 흐름: 엔진에서 최신 프레임 가져오기 → GPU 스레드에서 분할 → 엔진에서 추가.
hot loop 는 분할을 기다리지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from ..engine import Engine
from ..pipeline import VisionProcessor
from ..tracking.register import RegistrationError, register, register_line
from ..tracking.segment import Segmenter

Unit = Field(ge=0.0, le=1.0)


log = logging.getLogger(__name__)

class AddObject(BaseModel):
    box: list[float] | None = Field(None, min_length=4, max_length=4)
    point: list[float] | None = Field(None, min_length=2, max_length=2)
    line: list[float] | None = Field(None, min_length=4, max_length=4,
                                     description="펜: [펜촉 x, 펜촉 y, 반대쪽 끝 x, 반대쪽 끝 y]")
    name: str | None = Field(None, max_length=40)

    @model_validator(mode="after")
    def _check(self) -> AddObject:
        if sum(v is not None for v in (self.box, self.point, self.line)) != 1:
            raise ValueError("box, point, line 중 하나만 주세요")
        vals = self.box or self.point or self.line or []
        if any(not 0.0 <= v <= 1.0 for v in vals):
            raise ValueError("좌표는 0..1 로 정규화해야 합니다")
        if self.box is not None:
            x1, y1, x2, y2 = self.box
            self.box = [min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2)]
        return self


class PenBody(BaseModel):
    shadow_assist: bool | None = None
    contact_method: Literal["legacy", "floor"] | None = Field(
        None, description="수평 카메라 접촉 판정: legacy(기존 책상 면) | floor(바닥 기하+그림자+상태기계, 실험)")
    floor_depth_roll: bool | None = Field(None, description="깊이 모델(Depth Anything V2 Small)로 잰 카메라 롤을 바닥 평면 기울기로 쓴다 (기본 켬, 모델이 없으면 터치로 배운 롤)")
    horizon: float | None = Field(None, ge=-1.0, le=1.0, description="책상 소실선 높이 (프레임 높이 비율)")
    touch_on: float | None = Field(None, ge=0.1, le=3.0, description="접촉 문턱 (펜 굵기 배수)")
    touch_off: float | None = Field(None, ge=0.15, le=4.0)
    tip_min_cutoff: float | None = Field(None, ge=0.2, le=10)
    tip_beta: float | None = Field(None, ge=0, le=5)
    edge_span: float | None = Field(None, ge=0, le=1.5)
    refined_max_age: float | None = Field(None, ge=0.05, le=2)
    desk_contact_margin: float | None = Field(None, ge=0, le=.9)


class Candidate(BaseModel):
    index: int = Field(ge=0, le=16)


class Rename(BaseModel):
    name: str = Field(min_length=1, max_length=40)


class MemoryItem(BaseModel):
    kind: Literal["registration", "anchor", "reacquired"]
    t: float


class ForgetMemory(BaseModel):
    items: list[MemoryItem] = Field(max_length=32)


def make_router(engine: Engine, processor: VisionProcessor, segmenter: Segmenter) -> APIRouter:
    r = APIRouter(prefix="/api/objects")

    async def on_engine(fn):  # type: ignore[no-untyped-def]
        return await asyncio.wrap_future(engine.submit(fn))

    async def do_register(frame, req: dict[str, Any], candidate: int | None):  # type: ignore[no-untyped-def]
        w, h = frame.size
        box = point = None
        if req.get("line"):
            ln = req["line"]
            tip, tail = (ln[0] * w, ln[1] * h), (ln[2] * w, ln[3] * h)
            try:
                return await asyncio.to_thread(register_line, frame.image, segmenter, tip, tail)
            except RegistrationError as exc:
                raise HTTPException(422, str(exc)) from exc
        if req.get("box"):
            b = req["box"]
            box = (b[0] * w, b[1] * h, b[2] * w, b[3] * h)
        else:
            point = (req["point"][0] * w, req["point"][1] * h)
        scene = await on_engine(processor.scene_snapshot)  # 정지 배경 모델: 배경 그대로인 곳으로 번진 후보를 덜 고른다
        if scene is not None and scene.shape[:2] != frame.image.shape[:2]:
            scene = None
        try:
            return await asyncio.to_thread(register, frame.image, segmenter, box, point, candidate, scene)
        except RegistrationError as exc:
            raise HTTPException(422, str(exc)) from exc

    async def auto_reseg_once() -> int:
        """재추적 뒤 가만히 있거나 오래 가만히 있는 물체를 지금 프레임·지금 박스로 다시 분할한다 ('다시 선택' 과 같은 경로:
        id·이름·매핑·마우스 연결 유지). 새 마스크가 지금 추적 박스와 크게 다르면(다른 물체를 잡음) 버린다. 처리한 수를 돌려준다."""
        jobs = await on_engine(processor.auto_reseg_jobs)
        done = 0
        for oid, prompt, cand, why, since in jobs:
            ok = False
            try:
                obj, frame, generation, source = await on_engine(
                    lambda: (processor.objects.get(oid), processor.snapshot(), processor.generation, engine.source))
                if obj is None or frame is None:
                    continue
                try:
                    reg = await do_register(frame, prompt, cand)
                except HTTPException:
                    continue
                cur = obj.out.box

                def _apply():  # type: ignore[no-untyped-def]
                    if (generation != processor.generation or source is not engine.source
                            or processor.objects.get(oid) is not obj or not processor.auto_reseg_still(oid, since)):
                        return False
                    if cur is not None:
                        from ..tracking.api import box_iou
                        a0 = max(1.0, (cur[2] - cur[0]) * (cur[3] - cur[1]))
                        b = reg.measure.box
                        a1 = (b[2] - b[0]) * (b[3] - b[1])
                        if box_iou(tuple(b), tuple(cur)) < 0.5 or not 0.5 < a1 / a0 < 2.0:
                            return False
                    o = processor.reselect(oid, frame, reg, prompt)
                    o.reg_frame = frame  # type: ignore[attr-defined]  # 후보 바꾸기도 새 프레임 기준
                    log.info("auto re-segmentation: object %s (%s)", oid, why)
                    return True
                ok = bool(await on_engine(_apply))
                done += ok
            except Exception:
                log.exception("auto re-segmentation failed")
            finally:
                await on_engine(lambda: processor.auto_reseg_done(oid, ok))
        return done

    async def auto_reseg_loop() -> None:
        while True:
            await asyncio.sleep(0.25)
            if not processor.auto_reseg:
                continue
            try:
                await auto_reseg_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("auto re-segmentation loop")

    r.auto_reseg_once = auto_reseg_once  # type: ignore[attr-defined]
    r.auto_reseg_loop = auto_reseg_loop  # type: ignore[attr-defined]

    @r.get("")
    async def list_objects() -> list[dict[str, Any]]:
        return await on_engine(lambda: processor.state()["objects"])

    @r.post("", status_code=201)
    async def add(req: AddObject) -> dict[str, Any]:
        frame, generation, source = await on_engine(lambda: (processor.snapshot(), processor.generation, engine.source))
        if frame is None:
            raise HTTPException(409, "아직 카메라 프레임이 없습니다.")
        prompt = req.model_dump(exclude_none=True)
        reg = await do_register(frame, prompt, None)

        def _add():  # type: ignore[no-untyped-def]
            if generation != processor.generation or source is not engine.source:
                raise ValueError("분할 중 영상 소스가 바뀌었습니다. 새 영상에서 다시 선택하세요.")
            pen_line = None
            if req.line:
                w, h = frame.size
                ln = req.line
                pen_line = ((ln[0] * w, ln[1] * h), (ln[2] * w, ln[3] * h))
            obj = processor.add(frame, reg, prompt, req.name or ("펜" if pen_line else None), pen_line=pen_line)
            obj.reg_frame = frame  # type: ignore[attr-defined]  # 후보 바꾸기용
            return processor.object_info(obj)

        try:
            return await on_engine(_add)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.post("/{oid}/candidate")
    async def pick_candidate(oid: int, body: Candidate) -> dict[str, Any]:
        obj, source = await on_engine(lambda: (processor.objects.get(oid), engine.source))
        if obj is None:
            raise HTTPException(404, "no such object")
        frame = obj.reg_frame  # type: ignore[attr-defined]
        reg = await do_register(frame, obj.prompt, body.index)

        def _replace():  # type: ignore[no-untyped-def]
            if processor.objects.get(oid) is not obj or engine.source is not source:
                raise ValueError("분할 중 물체가 삭제되었거나 영상 소스가 바뀌었습니다. 다시 선택하세요.")
            pen_line = None
            if obj.kind == "pen" and obj.prompt.get("line"):
                w, h = frame.size
                ln = obj.prompt["line"]
                pen_line = ((ln[0] * w, ln[1] * h), (ln[2] * w, ln[3] * h))
            # A candidate changes the object's shape, not its identity or connections.
            updated = processor.reselect(oid, frame, reg, obj.prompt, pen_line=pen_line)
            updated.reg_frame = frame  # type: ignore[attr-defined]
            return processor.object_info(updated)

        try:
            return await on_engine(_replace)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.post("/{oid}/reselect")
    async def reselect(oid: int, req: AddObject) -> dict[str, Any]:
        """다시 선택: 같은 id 로 현재 프레임에서 다시 분할해 모양을 다시 기억한다.
        id·이름·색·매핑·마우스 연결은 그대로. 펜은 두 점(line), 일반 물체는 박스나 점."""
        obj, frame, generation, source = await on_engine(
            lambda: (processor.objects.get(oid), processor.snapshot(), processor.generation, engine.source))
        if obj is None:
            raise HTTPException(404, "no such object")
        if (obj.kind == "pen") != (req.line is not None):
            raise HTTPException(422, "펜은 펜촉·반대쪽 끝 두 점을, 일반 물체는 박스나 한 점을 주세요.")
        if frame is None:
            raise HTTPException(409, "아직 카메라 프레임이 없습니다.")
        prompt = req.model_dump(exclude_none=True, exclude={"name"})
        reg = await do_register(frame, prompt, None)

        def _reselect():  # type: ignore[no-untyped-def]
            if generation != processor.generation or source is not engine.source or processor.objects.get(oid) is not obj:
                raise LookupError("분할 중 물체가 삭제되었거나 영상 소스가 바뀌었습니다. 다시 선택하세요.")
            pen_line = None
            if req.line:
                w, h = frame.size
                ln = req.line
                pen_line = ((ln[0] * w, ln[1] * h), (ln[2] * w, ln[3] * h))
            o = processor.reselect(oid, frame, reg, prompt, pen_line=pen_line)
            o.reg_frame = frame  # type: ignore[attr-defined]  # 후보 바꾸기도 새 프레임 기준
            return processor.object_info(o)

        try:
            return await on_engine(_reselect)
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @r.delete("/{oid}", status_code=204)
    async def delete(oid: int) -> None:
        try:
            await on_engine(lambda: processor.remove(oid))
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc

    @r.post("/{oid}/neutral")
    async def neutral(oid: int) -> dict[str, Any]:
        def _n():  # type: ignore[no-untyped-def]
            processor.set_neutral(oid)
            return processor.object_info(processor.objects[oid])

        try:
            return await on_engine(_n)
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc

    @r.post("/{oid}/pen/{action}")
    async def pen_action(oid: int, action: str, body: PenBody | None = None) -> dict[str, Any]:
        """펜 전용: clear(그림 지우기) · touch(지금 닿아 있음 → 보정) · reset(보정 초기화) · config(소실선 등)"""
        def _do():  # type: ignore[no-untyped-def]
            if processor.auto_calibration and processor.auto_calibration.active:
                raise ValueError('자동 보정을 마치거나 취소한 뒤 펜 설정을 변경하세요.')
            pen = processor.pens.get(oid)
            if pen is None:
                raise KeyError(oid)
            if action == "clear":
                pen.clear()
            elif action == "touch":
                if not pen.mark_touching():
                    raise ValueError('펜을 1초 동안 안정적으로 댄 뒤 다시 눌러 주세요.' if pen.overhead else
                                     "보정하려면 가까운 곳과 먼 곳, 두 군데 이상에서 펜을 대고 눌러 주세요.")
            elif action == 'lift':
                if not pen.mark_lifted():
                    raise ValueError('Desk View에서 펜을 2–3cm 들고 1초 유지한 뒤 눌러 주세요.')
            elif action in ('down', 'up'):
                if not pen.overhead:
                    raise ValueError('수동 그리기 버튼은 Desk View 모드에서 사용합니다.')
                pen.manual_press(action == 'down', time.monotonic())
            elif action == 'auto':
                pen.manual_contact = pen.manual_until = None
                pen.lift()
            elif action == "reset":
                pen.reset_calibration()
            elif action == "config" and body is not None:
                if body.contact_method is not None and body.contact_method != pen.cfg.contact_method:
                    pen.lift()  # 방식이 바뀌면 진행 중인 획을 닫고 새 방식으로 처음부터 판정한다
                    pen.cfg.contact_method = body.contact_method
                if body.floor_depth_roll is not None:
                    pen.cfg.floor_depth_roll = body.floor_depth_roll
                if body.shadow_assist is not None:
                    pen.cfg.shadow_assist = body.shadow_assist
                    pen.desk_near_s = None
                if body.horizon is not None:
                    pen.cfg.horizon = body.horizon
                if body.touch_on is not None:
                    pen.cfg.touch_on = body.touch_on
                    pen.cfg.touch_off = max(pen.cfg.touch_off, body.touch_on * 1.3)
                if body.touch_off is not None:
                    pen.cfg.touch_off = max(body.touch_off, pen.cfg.touch_on * 1.3)
                if body.tip_min_cutoff is not None or body.tip_beta is not None:
                    from ..tracking.smooth import OneEuro
                    pen.cfg.tip_min_cutoff = body.tip_min_cutoff or pen.cfg.tip_min_cutoff
                    pen.cfg.tip_beta = body.tip_beta if body.tip_beta is not None else pen.cfg.tip_beta
                    pen.fx = OneEuro(pen.cfg.tip_min_cutoff, pen.cfg.tip_beta)
                    pen.fy = OneEuro(pen.cfg.tip_min_cutoff, pen.cfg.tip_beta)
                if body.edge_span is not None:
                    pen.cfg.edge_span = body.edge_span
                if body.refined_max_age is not None:
                    pen.cfg.refined_max_age = body.refined_max_age
                if body.desk_contact_margin is not None:
                    pen.cfg.desk_contact_margin = body.desk_contact_margin
            else:
                raise LookupError(action)
            return {"id": oid, **pen.state(consume=False)}

        try:
            return await on_engine(_do)
        except KeyError as exc:
            raise HTTPException(404, "펜으로 등록된 물체가 아닙니다.") from exc
        except LookupError as exc:
            raise HTTPException(404, f"unknown pen action {action}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/{oid}/pen/floor-map")
    async def floor_map(oid: int) -> dict[str, Any]:
        """바닥 그라데이션 맵 (개발자 보기): 펜이 닿을 때의 예상 굵기를 바닥 영역에 흑백으로. floor 접촉 판정 전용."""
        def _do():  # type: ignore[no-untyped-def]
            pen = processor.pens.get(oid)
            if pen is None:
                raise KeyError(oid)
            frame, obj = processor.snapshot(), processor.objects.get(oid)
            mask = None if obj is None else obj.out.mask
            return pen.floor_map(None if frame is None else frame.image, mask)

        try:
            return await on_engine(_do)
        except KeyError as exc:
            raise HTTPException(404, "펜으로 등록된 물체가 아닙니다.") from exc

    @r.get("/{oid}/memory")
    async def memory(oid: int) -> dict[str, Any]:
        """물체 기억: 놓쳤을 때 복귀에 쓰는 등록 모습·Tier 1 앵커·재획득 순간의 그림과 모양·색 기억."""
        try:
            return await on_engine(lambda: processor.object_memory(oid))
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.get("/{oid}/thumbnail")
    async def thumbnail(oid: int) -> dict[str, Any]:
        """물체 패널 사진 카드용 등록 모습 (없으면 image=null)."""
        try:
            return {"id": oid, "image": await on_engine(lambda: processor.object_thumbnail(oid))}
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc

    @r.post("/{oid}/memory/forget")
    async def memory_forget(oid: int, body: ForgetMemory) -> dict[str, Any]:
        """체크한 기억(AI 앵커·재획득)을 지운다. 등록 모습은 지우지 않는다."""
        items = [(i.kind, i.t) for i in body.items]
        try:
            return await on_engine(lambda: processor.forget_object_memory(oid, items))
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc
        except LookupError as exc:
            raise HTTPException(409, str(exc)) from exc

    @r.patch("/{oid}")
    async def rename(oid: int, body: Rename) -> dict[str, Any]:
        def _r():  # type: ignore[no-untyped-def]
            processor.rename(oid, body.name)
            return processor.object_info(processor.objects[oid])

        try:
            return await on_engine(_r)
        except KeyError as exc:
            raise HTTPException(404, "no such object") from exc

    return r
