export const EMPTY_VALUE = "-";

const ACTION_LABELS: Record<string, string> = {
  BUY: "Achat",
  SELL: "Vente",
  HOLD: "Attente",
  NO_TRADE: "Pas de trade",
};

const TRADE_STATUS_LABELS: Record<string, string> = {
  OPEN: "Ouverte",
  CLOSED: "Fermée",
  CANCELLED: "Annulée",
};

const RECONCILIATION_STATUS_LABELS: Record<string, string> = {
  matched: "Matchée",
  missing_on_broker: "Absente broker",
  closed_from_broker: "Clôturée broker",
  untracked: "Non suivie",
};

const REGIME_LABELS: Record<string, string> = {
  BULLISH_TREND: "Tendance haussière",
  BEARISH_TREND: "Tendance baissière",
  RANGE: "Range",
  HIGH_VOLATILITY: "Forte volatilité",
  LOW_DATA_QUALITY: "Qualité des données faible",
  UNKNOWN: "Inconnu",
  BULLISH_HIGH_VOLATILITY: "Haussier volatil",
  BEARISH_HIGH_VOLATILITY: "Baissier volatil",
};

const TREND_LABELS: Record<string, string> = {
  BULLISH: "Haussier",
  BEARISH: "Baissier",
  RANGE: "Range",
  UNKNOWN: "Inconnu",
};

const VOLATILITY_LABELS: Record<string, string> = {
  HIGH_VOLATILITY: "Forte volatilité",
  NORMAL_VOLATILITY: "Volatilité normale",
  LOW_VOLATILITY: "Faible volatilité",
  UNKNOWN_VOLATILITY: "Volatilité inconnue",
};

const GATE_STATUS_LABELS: Record<string, string> = {
  ALLOWED: "Autorisé",
  BLOCKED: "Bloqué",
  NOT_APPLICABLE: "Non applicable",
};

const AGREEMENT_LABELS: Record<string, string> = {
  ALIGNED: "Aligné",
  CONFLICT: "Conflit",
  NEUTRAL: "Neutre",
  UNKNOWN: "Inconnu",
};

const EXECUTION_MODE_LABELS: Record<string, string> = {
  PAPER: "Paper",
  DEMO: "Démo",
  LIVE: "Live",
};

const STRATEGY_LABELS: Record<string, string> = {
  "expected-return-paper": "Expected-return paper",
  "expected-return-paper-regime-shadow": "Shadow régime",
  lightgbm: "LightGBM",
  hold: "Attente",
};

export function labelFrom(map: Record<string, string>, value?: string | null) {
  if (!value) return EMPTY_VALUE;
  return map[value] ?? value;
}

export function actionLabel(value?: string | null) {
  return labelFrom(ACTION_LABELS, value);
}

export function tradeStatusLabel(value?: string | null) {
  return labelFrom(TRADE_STATUS_LABELS, value);
}

export function reconciliationStatusLabel(value?: string | null) {
  return labelFrom(RECONCILIATION_STATUS_LABELS, value);
}

export function regimeLabel(value?: string | null) {
  return labelFrom(REGIME_LABELS, value);
}

export function trendLabel(value?: string | null) {
  return labelFrom(TREND_LABELS, value);
}

export function volatilityLabel(value?: string | null) {
  return labelFrom(VOLATILITY_LABELS, value);
}

export function gateStatusLabel(value?: string | null) {
  return labelFrom(GATE_STATUS_LABELS, value);
}

export function agreementLabel(value?: string | null) {
  return labelFrom(AGREEMENT_LABELS, value);
}

export function executionModeLabel(value?: string | null) {
  return labelFrom(EXECUTION_MODE_LABELS, value);
}

export function strategyLabel(value?: string | null) {
  return labelFrom(STRATEGY_LABELS, value);
}

export function humanizeText(value?: string | null) {
  if (!value) return EMPTY_VALUE;
  return value
    .replaceAll("expected-return-paper-regime-shadow", strategyLabel("expected-return-paper-regime-shadow"))
    .replaceAll("expected-return-paper", strategyLabel("expected-return-paper"))
    .replaceAll("expected-return", "rendement attendu")
    .replaceAll("BULLISH_TREND", regimeLabel("BULLISH_TREND"))
    .replaceAll("BEARISH_TREND", regimeLabel("BEARISH_TREND"))
    .replaceAll("LOW_DATA_QUALITY", regimeLabel("LOW_DATA_QUALITY"))
    .replaceAll("HIGH_VOLATILITY", regimeLabel("HIGH_VOLATILITY"))
    .replaceAll("NORMAL_VOLATILITY", volatilityLabel("NORMAL_VOLATILITY"))
    .replaceAll("LOW_VOLATILITY", volatilityLabel("LOW_VOLATILITY"))
    .replaceAll("NO_TRADE", actionLabel("NO_TRADE"))
    .replaceAll("BUY", actionLabel("BUY"))
    .replaceAll("SELL", actionLabel("SELL"))
    .replaceAll("HOLD", actionLabel("HOLD"))
    .replaceAll("TRADING_ENABLED=false", "ordres bloqués")
    .replaceAll("paper_only=True", "paper-only actif")
    .replaceAll("paper_only=true", "paper-only actif")
    .replaceAll("paper_only=False", "paper-only inactif")
    .replaceAll("paper_only=false", "paper-only inactif")
    .replaceAll("ordres=False", "ordres bloqués")
    .replaceAll("ordres=True", "ordres autorisés")
    .replaceAll("exclude_regime:", "Exclure régime : ");
}
