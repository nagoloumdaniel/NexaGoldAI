-- CreateTable
CREATE TABLE "RiskDecision" (
    "id" TEXT NOT NULL,
    "time" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "decisionId" TEXT,
    "approved" BOOLEAN NOT NULL,
    "reason" TEXT NOT NULL,
    "units" DECIMAL(12,2),
    "riskStats" JSONB,

    CONSTRAINT "RiskDecision_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "TradeResult" (
    "id" TEXT NOT NULL,
    "tradeId" TEXT NOT NULL,
    "strategy" TEXT NOT NULL,
    "side" TEXT NOT NULL,
    "entryTime" TIMESTAMP(3) NOT NULL,
    "exitTime" TIMESTAMP(3) NOT NULL,
    "entryPrice" DECIMAL(12,3) NOT NULL,
    "exitPrice" DECIMAL(12,3) NOT NULL,
    "pnl" DECIMAL(12,2) NOT NULL,
    "resultR" DECIMAL(8,4),
    "mfeR" DECIMAL(8,4),
    "maeR" DECIMAL(8,4),
    "holdingSeconds" INTEGER NOT NULL,
    "exitSource" TEXT,
    "details" JSONB,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "TradeResult_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "SystemEvent" (
    "id" TEXT NOT NULL,
    "time" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "eventType" TEXT NOT NULL,
    "severity" TEXT NOT NULL,
    "component" TEXT NOT NULL,
    "message" TEXT NOT NULL,
    "payload" JSONB,

    CONSTRAINT "SystemEvent_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "RiskDecision_time_idx" ON "RiskDecision"("time");

-- CreateIndex
CREATE INDEX "RiskDecision_approved_time_idx" ON "RiskDecision"("approved", "time");

-- CreateIndex
CREATE UNIQUE INDEX "TradeResult_tradeId_key" ON "TradeResult"("tradeId");

-- CreateIndex
CREATE INDEX "TradeResult_exitTime_idx" ON "TradeResult"("exitTime");

-- CreateIndex
CREATE INDEX "TradeResult_strategy_exitTime_idx" ON "TradeResult"("strategy", "exitTime");

-- CreateIndex
CREATE INDEX "SystemEvent_time_idx" ON "SystemEvent"("time");

-- CreateIndex
CREATE INDEX "SystemEvent_eventType_time_idx" ON "SystemEvent"("eventType", "time");
