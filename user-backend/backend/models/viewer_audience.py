"""Match-local viewer selection; separate from account defaults."""
from typing import Literal

from .audiences import StrictModel


class ViewerAudience(StrictModel):
    team: Literal['home', 'away', 'neutral']
    fan_style: Literal['analytical', 'simple', 'casual', 'experienced']
