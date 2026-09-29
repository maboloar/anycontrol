import numpy as np
import pytest
from .test_server import client
from vision_input.io.mouse import MouseController, MouseSettings
from vision_input.io.sink import VirtualSink
from vision_input.pen import PenConfig, PenTracker


def test_game_setup_uses_absolute_position_and_preserves_other_mouse_settings(client):
    with client.websocket_connect('/ws') as ws:
        for _ in range(100):
            if ws.receive().get('bytes'):
                break
    added = client.post('/api/objects', json={'box': [.2, .2, .55, .65]}).json()
    oid = added['id']
    profile = {'version': 1, 'name': 'position test', 'mappings': []}
    response = client.post('/api/game-setup', json={'object_id': oid, 'position': True, 'profile': profile})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data['mouse']['settings']['mode'] == 'object'
    assert data['mouse']['settings']['coordinate_mode'] == 'image'
    assert data['mouse']['settings']['pen_relative'] is False
    assert data['mapping']['mode'] == 'send'
    assert client.get('/api/real').json()['state'] == 'off'
    response = client.post('/api/game-setup', json={'object_id': oid, 'position': False, 'profile': profile})
    assert response.json()['mouse']['settings']['mode'] == 'off'
    response = client.post('/api/game-setup', json={'object_id': 99999, 'position': True, 'profile': profile})
    assert response.status_code == 409


def test_global_mirror_api_does_not_rewrite_individual_mouse_settings(client):
    assert client.get('/api/tracking').json()['input_mirror'] is True
    before = client.get('/api/mouse').json()['settings']
    response = client.put('/api/tracking', json={'input_mirror': True})
    assert response.status_code == 200 and response.json()['input_mirror'] is True
    assert client.get('/api/mouse').json()['settings'] == before
    assert client.put('/api/tracking', json={'input_mirror': False}).json()['input_mirror'] is False


@pytest.mark.parametrize('local,global_,expected', [(False,False,.2),(True,False,.8),(False,True,.8),(True,True,.2)])
def test_mouse_global_and_individual_mirrors_compose(local, global_, expected):
    m = MouseController(VirtualSink())
    m.configure(MouseSettings(mirror=local))
    m.input_mirror = global_
    assert m._map(np.array([.2,.4]), [0,0,1,1])[0] == pytest.approx(expected)


def test_shadow_veto_only_blocks_new_stroke_and_never_manual_press(monkeypatch):
    pen = PenTracker((100, 200), (80, 80), PenConfig(shadow_assist=True))
    pen.width = 10
    pen.y_hist.append(200.)
    pen.tip = np.array([100., 200.])
    monkeypatch.setattr(pen.surface, 'height', lambda *_: 0.)
    pen.desk_near_s = .2
    pen._decide(0)
    assert not pen.contact and pen.shadow_veto
    pen.desk_near_s = .9
    pen._decide(.1)
    assert pen.contact and not pen.shadow_veto
    pen.desk_near_s = .2
    pen._decide(.2)
    assert pen.contact and not pen.shadow_veto
    pen.lift()
    pen.manual_contact = True
    pen._decide(.3)
    assert pen.contact and not pen.shadow_veto
