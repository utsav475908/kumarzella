"""Import every model so Alembic and SQLAlchemy see the full metadata."""

from app.modules.accounts.models import Account, CashTransaction  # noqa: F401
from app.modules.attachments.models import Attachment  # noqa: F401
from app.modules.audit.models import AuditEvent  # noqa: F401
from app.modules.auth.models import User, UserSession  # noqa: F401
from app.modules.executions.models import Execution  # noqa: F401
from app.modules.imports.models import ImportJob, RawImportRecord  # noqa: F401
from app.modules.instruments.models import Instrument  # noqa: F401
from app.modules.journal.models import DayNote, Tag, TradeNote, TradeTag  # noqa: F401
from app.modules.playbooks.models import Playbook  # noqa: F401
from app.modules.trades.models import Position, Trade, TradeExecution  # noqa: F401
