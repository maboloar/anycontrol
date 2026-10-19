import { t } from '../i18n';

/** Identify experimental pen input without marking bare-hand input as beta. */
export function BetaBadge() {
  return <> {' '}<span className="beta-badge" aria-label="Beta"
    title={t('펜 입력은 Beta 기능입니다. 펜촉과 접촉 판정은 환경에 따라 달라질 수 있습니다.', 'Pen input is in Beta. Tip tracking and contact detection may vary with your setup.')}>Beta</span></>;
}
