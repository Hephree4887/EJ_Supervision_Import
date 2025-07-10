"""Financial database import."""

import logging
from utils.logging_helper import setup_logging, operation_counts
from dotenv import load_dotenv
from etl.configurable_importer import ConfigurableDBImporter

logger = logging.getLogger(__name__)

PREPROCESS_STEPS = [
    ("GatherFeeInstanceIDs", "financial/gather_feeinstanceids.sql"),
]

IMPORTER = ConfigurableDBImporter(
    db_type="Financial",
    preprocessing_steps=PREPROCESS_STEPS,
    gather_drop_select_script="financial/gather_drops_and_selects_financial.sql",
    update_joins_script="financial/update_joins_financial.sql",
    next_step="LOB Column Processing",
)


def main() -> bool:
    setup_logging()
    load_dotenv()
    result = IMPORTER.run()
    logger.info(
        "Run completed - successes: %s failures: %s",
        operation_counts["success"],
        operation_counts["failure"],
    )
    return result


if __name__ == "__main__":
    main()
