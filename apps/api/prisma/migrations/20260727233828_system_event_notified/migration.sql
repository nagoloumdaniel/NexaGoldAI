-- AlterTable
ALTER TABLE "SystemEvent" ADD COLUMN     "notified" BOOLEAN NOT NULL DEFAULT false;

-- CreateIndex
CREATE INDEX "SystemEvent_notified_time_idx" ON "SystemEvent"("notified", "time");
