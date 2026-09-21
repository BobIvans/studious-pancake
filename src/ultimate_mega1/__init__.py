"""ULTIMATE-MEGA1 advanced research and qualification contracts.

All public child contracts are offline/read-only by default.  Importing this
package grants no signer, sender, capital, network or live authority.
"""

from .manifest import ALL_FUNCTIONS, CHILDREN, FUNCTION_COUNT, NF_IDS

__all__ = ["ALL_FUNCTIONS", "CHILDREN", "FUNCTION_COUNT", "NF_IDS"]
