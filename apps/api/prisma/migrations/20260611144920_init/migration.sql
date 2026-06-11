-- CreateEnum
CREATE TYPE "TradeSide" AS ENUM ('BUY', 'SELL');

-- CreateEnum
CREATE TYPE "TradeStatus" AS ENUM ('OPEN', 'CLOSED', 'CANCELLED');

-- CreateTable
CREATE TABLE "User" (
    "id" TEXT NOT NULL,
    "email" TEXT NOT NULL,
    "passwordHash" TEXT NOT NULL,
    "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updatedAt" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "User_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Trade" (
    "id" TEXT NOT NULL,
    "instrument" TEXT NOT NULL DEFAULT 'XAU_USD',
    "side" "TradeSide" NOT NULL,
    "units" DECIMAL(12,2) NOT NULL,
    "entryPrice" DECIMAL(12,3) NOT NULL,
    "exitPrice" DECIMAL(12,3),
    "stopLoss" DECIMAL(12,3),
    "takeProfit" DECIMAL(12,3),
    "pnl" DECIMAL(12,2),
    "status" "TradeStatus" NOT NULL DEFAULT 'OPEN',
    "strategy" TEXT NOT NULL,
    "reason" TEXT NOT NULL,
    "features" JSONB,
    "brokerTradeId" TEXT,
    "openedAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "closedAt" TIMESTAMP(3),

    CONSTRAINT "Trade_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "Candle" (
    "instrument" TEXT NOT NULL,
    "granularity" TEXT NOT NULL,
    "time" TIMESTAMP(3) NOT NULL,
    "open" DECIMAL(12,3) NOT NULL,
    "high" DECIMAL(12,3) NOT NULL,
    "low" DECIMAL(12,3) NOT NULL,
    "close" DECIMAL(12,3) NOT NULL,
    "volume" INTEGER NOT NULL,

    CONSTRAINT "Candle_pkey" PRIMARY KEY ("instrument","granularity","time")
);

-- CreateTable
CREATE TABLE "EquitySnapshot" (
    "id" TEXT NOT NULL,
    "time" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "balance" DECIMAL(14,2) NOT NULL,
    "nav" DECIMAL(14,2) NOT NULL,
    "drawdownPct" DECIMAL(6,3),

    CONSTRAINT "EquitySnapshot_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "StrategyDecision" (
    "id" TEXT NOT NULL,
    "time" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "strategy" TEXT NOT NULL,
    "action" TEXT NOT NULL,
    "confidence" DECIMAL(4,3) NOT NULL,
    "reason" TEXT NOT NULL,
    "features" JSONB,
    "executed" BOOLEAN NOT NULL DEFAULT false,
    "tradeId" TEXT,

    CONSTRAINT "StrategyDecision_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "User_email_key" ON "User"("email");

-- CreateIndex
CREATE INDEX "Trade_status_idx" ON "Trade"("status");

-- CreateIndex
CREATE INDEX "Trade_openedAt_idx" ON "Trade"("openedAt");

-- CreateIndex
CREATE INDEX "EquitySnapshot_time_idx" ON "EquitySnapshot"("time");

-- CreateIndex
CREATE INDEX "StrategyDecision_strategy_time_idx" ON "StrategyDecision"("strategy", "time");
