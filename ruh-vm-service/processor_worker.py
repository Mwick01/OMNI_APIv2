from __future__ import annotations

import logging

import database
from ai_processor import UnsupportedNoticeFile, analyze_notice
from config import PROCESS_BATCH_SIZE, PROCESSING_STALE_MINUTES, WHATSAPP_GROUP_IDS

logger = logging.getLogger(__name__)


def run_processor_cycle() -> None:
    database.init_db()
    recovered = database.recover_stale_processing(PROCESSING_STALE_MINUTES)
    if recovered:
        logger.warning("Recovered %d stale processing job(s)", recovered)

    rows = database.claim_processing_batch(PROCESS_BATCH_SIZE)
    if not rows:
        logger.info("No notices waiting for AI processing")
        return

    for row in rows:
        notice_id = int(row["id"])
        try:
            data = analyze_notice(row["title"], row["file_path"], row["file_type"])
            database.mark_analysis_success(notice_id, data)
            database.ensure_group_deliveries(notice_id, WHATSAPP_GROUP_IDS)
            logger.info("Analyzed and queued deliveries: %s", row["title"][:100])
        except UnsupportedNoticeFile as exc:
            database.mark_ready_without_analysis(notice_id, str(exc))
            database.ensure_group_deliveries(notice_id, WHATSAPP_GROUP_IDS)
            logger.warning("Sending without AI analysis: %s", exc)
        except Exception as exc:
            exhausted = database.mark_analysis_failure(notice_id, str(exc))
            if exhausted:
                database.ensure_group_deliveries(notice_id, WHATSAPP_GROUP_IDS)
                logger.exception("AI retries exhausted; queued original notice: %s", row["title"][:100])
            else:
                logger.exception("AI analysis failed and will retry: %s", row["title"][:100])
