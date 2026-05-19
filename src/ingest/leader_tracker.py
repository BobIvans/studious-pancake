"""Leader Schedule Tracker for Hybrid Execution Engine."""

import asyncio
import logging
from typing import Dict, Optional
import aiohttp
from solders.pubkey import Pubkey

logger = logging.getLogger(__name__)

class LeaderTracker:
    """Tracks slot leader schedule for hybrid execution."""

    # Jito validator vote accounts from API
    JITO_VALIDATOR_VOTES = [
        "7Eg46UwGgsufXdd9C9kF27UAyD2t4VdmCdVTtPFoqxCy",
        "shft7Fry1js37Hm9wq4dfwcZSp2DyKszeWMvEpjYCQ1",
        "DkZehyHr92C4wHYfoXJU6FpKFVeh64LRgkJmFKYub4UV",
        "2DNGsVZ9rg6RvT8bY4SGmGvyiVJ4xt9RL3NDd6uhfN46",
        "DfpdmTsSCBPxCDwZwgBMfjjV8mF8xHkGRcXP8dJBVmrq",
        "HdQ1Ap8wm6Mz65FaP8jMNBVfCDv5T9NdS8UTSvHmcotn",
        "XeUEzvZb2FUptF",  # Truncated in output, but using as is
        "DzPT1ZWDeURdTj38QBSceWnrpYFxZRBLPRXmUgHVDAGR",
        "stsaYQJUhKZDHSqndGtgo6jgbhVaHBSHhtfVWxCwrhD",
        "8UHnwrLihP4q1fZjAYGCZdGgtAkCaFiDLXa33r7niRjD",
        "CcaHc2L43ZWjwCHART3oZoJvHLAe9hzT2DJNUpBzoTN1",
        "21wUViiyG1g47VZ39ZZsSkFX9nu6bkyfy6jryHGD2TUB",
        "MS1kjUoVPfy4AgyJLiJ3eC6Gv34Cwr839MryJgNKdwJ",
        "3ZYJxzCeweSoh2Jj7oCgencFs9y27iKmXJeqYapje1cj",
        "8jxSHbS4qAnh5yueFp4D9ABXubKqMwXqF3HtdzQGuphp",
        "H1kyn75BFTXr8QRmToRRvuEEmYan5n6M5APyfhMLau3b",
        "kyvvvkDpDCtSxQMPhzRhmv14DgUBVEGGzn8Dnb8ircP",
        "CatzoSMUkTRidT5DwBxAC2pEtnwMBTpkCepHkFgZDiqb",
        "9RXDftY5xyhtYyzk4z7U9ddvBF2Z8DMfXmV6P6du9dxS",
        "9DR48EtgDzh3Gx5HiiQikZn9c2y12casm1bcUMuurV2x",
        "4BVYjw1ztUzUPsxsaCheWWwThT2X4rjogZytGnuWPUGg",
        "94EhHE7MaKHq4p8oFADeyizDjwYwgFn1YBYGky8mR35z",
        "CHiaohVV2SQCFhiYP73iQzWT6HxnZqnAZJJqAYTeLAo",
        "2ZP7DPXW6gwMRSY9PSXQ75fZLrk4gKWKnT85pK5sVPa5",
        "3a2onvgTpGynakAQwx6gigtSeL7itZewNxqb5JiAvWeA",
        "eyeVhGmVEoPSWmQU2wP5WZmMihPBTCk7kMMm4VhuAKS",
        "DumiCKHVqoCQKD8roLApzR5Fit8qGV5fVQsJV9sTZk4a",
        "685Njwvpn3t5a8cAfVj7R65AfCJ6XoBpca9qy15XFiTd",
        "XzMLju7T6BSSngmsPogeuryd6uswiimkPU87gB2chho",
        "72LbWsZFEyB7xrB9ggeoPUrSw2vzPEnsPJJHZo1svkM7",
        "FLCrbfbwEhFARa8nK9rnZw8BVtKNAuHujh9EhWy5A4U4",
        "3ZUQekqiZoybB57y49eqtvSaoonqDwuNbeqEGwN88JkQ",
        "DsiG71AvUHUEo9rMMHqM9NAWQ6ptguRAHyot6wGzLJjx",
        "AbacusTT3yhEFEKkQKjGStDhKDnvSFGpg9EqBwz8FnDF",
        "PKvGYwh4efgythYddWAqGaPVuoZt8ybk7eXEoUqWxuA",
        "Cw2b2ng2fa78ndCXHcJMT1pqvdGxUHu5EBEB8KBshrk",
        "FsT844wGgZg7wGUQPVRdBFoDkMC6bj7Zp5Q3i8sZadWP",
        "9sWYTuuR4s12Q4SuSfo5CfWaFggQwA6Z8pf8dWowN5rk",
        "BbM5kJgrwEj3tYFfBPnjcARB54wDUHkXmLUTkazUmt2x",
        "76nwV8zz8tLz97SBRXH6uwHvgHXtqJDLQfF66jZhQ857",
        "R2D2vs3bJwpNF2ejaB6UW1JdCZ5VstuAmuwxDuUUWNj",
        "6anBvYWGwkkZPAaPF6BmzF6LUPfP2HFVhQUAWckKH9LZ",
        "7X7oVv6K6wawMNzVriczSAEk18GzqyrYrvqyJbwLAY3s",
        "AZoCYB4VgoM9DR9f1ZFcBn8xPSbtbqoxZnKJR7tkvEoX",
        "8LMatbjxgUW1S7CyuBhGk89BC9vhRzCRLwtXbyJru4Qi",
        "D9BcS9Fasxj7zNv3kP5rHErv7aFxihi5EBZo9xUqaHeh",
        "89DXJe6XTDASsmyXJoPyRetLq1csRj9N2Bwn67fNvYGt",
        "HeTyhZdUKswQoonJJTXqAnDN48ceyVAeFaKfYKayGPNS",
        "3tUZu4CkwMLwYdosoGc85n48VgDMyZVkL1VUJc7DrxW",
        "GEM1N1pCDGKiTa547eckcwuHWYMsUQeXgnXHfEZLDvpB",
        "FKBPfTuoqdF9yTmMJowTukend68EnyWXQXdc5Cxd5rSa",
        "BULKEEKf9Hjy4nwCthjzheEk4joH23LLXttAHjqEZmB2",
        "CzmqDuqEpfnkptuLAcikmJrhCnhFXo8aUBj6Rto1SPAc",
        "RaydiumJDX8X6om6Fg44xyqz5eukZ9KC3LX61SttLbH",
        "9G19HT8xqceG7mKQVSrTRS3DGnGqDHErPyQEaEfyWEuW",
        "AuBB9st3RqhHBkzZgBSm6SVnHZNJQSHeBWCSkik4bzdA",
        "BdM7KCd6ZYWcaCMmHVi8YeL4jFzDVM9cRLJUeRAGSvMS",
        "mnvkHm47ZmRKoSWuQZAfXLRiDPiKCq8PWkMWrp1Wwqe",
        "Fhks5gukimP6vxKYbRY4V1aw888EgHhpdDSscD9V6bub",
        "SBLZib4npE7svxFA7AsD3ytdQAfYNb39c8zsU82AA2E",
        "H2tJNyMHnRF6ahCQLQ1sSycM4FGchymuzyYzUqKEuydk",
        "9wQQnnnkk5b5GkQWTW9L4kEA3CjFv6CshQF2y6L276kN3",
        "8mu3JHHF1Qkcrbqjo6KWxyWvTxarZjqptJTokR2jrDFo",
        "HMV14UAuULSwqmZhsKHzaVkYAd94iWpEeURgbUegfQLc",
        "chdv8H9fPfk2zFqSVaxRjsEo2qEDmswbju3BVgAHPNb",
        "H7fXvnLCKtZqJBTipxeseabGfAZUdHJ9XuP6hCKrbvUb",
        "BU5CXmHhXwZfSYwFjCjqAqdbu7MTUsiKLUj45RSXiPsE",
        "49ufmzpErLmn7jAeP666i8nMdXhFuvzjCbQwf2oEMkN3",
        "BrRf2kyJEuW8TgdeDjvJcKK4NzTzRtM9RB6WuVKXHxkN",
        "AaVsZUEnrHUZoXC2oVgTY3GF5GGhzCTBGrjpBtuUWy1H",
        "CzGLRXJXoDo9q86MpphPVNNsTgAxHvZfUfAiouWDH89M",
        "26pV97Ce83ZQ6Kz9XT4td8tdoUFPTng8Fb8gPyc53dJx",
        "2QE9X9X4tdDUTYic1DgBBJjU7cWUNPbKYGerCb9KqDQN",
        "G1EAMrJcvzs5SwqAQRgDTjYBEGrxxJVwNS7qiUtB3akg",
        "2NxEEbhqqj1Qptq5LXLbDTP5tLa9f7PqkU8zNgxbGU9P",
        "53RJBy7aBGA7Aag6AryxEmBbsHDgwfBWagLrPbGHnfvR",
        "6XiVWAyRpG7wGUQPVRd2XrYdgQVQyoQamd2J8XAmate",
        "5K8qgC9nHzKHSSyo9fKLsMfYmavYdMgEaYx86cMmVKVv",
        "53ANFYA6BCDzdtiEeWawm5bqsH1Qgmjog8oMo5N4o4wU",
        "6q1VNp8Vy2Go12vb8CwbjUqqj2SXr2JYftJRWs71sW23",
        "5daP6pZoPSak6UEKuRg2HHjvTPpqqwB113oNamGNKuuZ",
        "dstqVmt3cDH43Ux2SeTY2Hza1eVW6pwGLwehWCLfuPd",
        "jntrMCSkeNagaMM437fhZxLYbFJh6pvj68bQDZx2pXf",
        "6D2jqw9hyVCpppZexquxa74Fn33rJzzBx38T58VucHx9",
        "GdSJPrzj8q1QJV53s1cHMcpbPhodgB9kjG7X9kq8Z56r",
        "323d4ZiSqS1PwGwpJwD88jNPaGqkm7YYW2tJt2TsqQ2",
        "G1juWDqojmp5CWDhgRqtXrtpAFw9xqhjmEQAKr9faf4V",
        "J1to1yufRnoWn81KYg1XkTWzmKjnYSnmE2VY8DGUJ9Qv",
        "DPmsofVJ1UMRZADgwYAHotJnazMwohHzRHSoomL6Qcao",
        "8vyuJTHSDkx7n8WbbcyQwq7i5btv",  # Truncated
        "6frBSsexBMZNKAaQY9dMKhyCu83Px54aL9SZWtuJWeWV",
        "dcntrKBwh8j5yL62Eg96Z5QjJWv3UXxMu4rqL82w6Cb",
        "8tjRQLzor4dP4qd1e7pVDdQmsdwdVv4kSeCVEHwWEiQW",
        "kaosFcskhYZCQidKKmkUSQLAqwpz3vtPpyyZ67N5NwA",
        "CarbnAxSfvsBdp6otKtoUa8XmUaX9PcsGq6Rto1SPFr",
        "2LrSZWeyvFovnzVFpFPQE7Lxt64xs3s3Re9HLxMJtGwf",
        "bkpkQKgJMQXqwZL5dRX9LMwnsz9zkZZqCtqWfnBcwDx",
        "JnGGar3XbAN6J3cKGRbNajCuhqnc9XWrk6WWr6hDmuM",
        "71nnaeTyVeA4pTozAPjRuQyMydQTZCrFUkz7Pzy5tiDJ",
        "FjkSLYmi6BJAJQn1iSLUGrPrBQjMaD4y1DVdnv3yaTsX",
        "DQ7D6ZRtKbBSxCcAunEkoTzQhCBKLPdzTjPRRnM6wo1f",
        "Gotas1PRPrkqqSNm1ZKcn8Tpx9qL8krSQzTZ5DPKzkFX",
        "4ibf8qJirtoBGg7gSD7V7CeCKoFB96PBYQ3J5QjSmAob",
        "8wTSPukwTAzNzEYyUdc8UiKkTg1hNtZ1xLum7o1Ne6wr",
        "9gANMngbGUmAaLXL1RC3JdiaLjRowJXNbzCTh53ht7mq",
        "Eajfs6oXGGkvjYsxkQZZJcDCLLkUajaHizfgg2xTsqyd",
        "SoLiDDVm88uWUMk2rQpG7B9wC55a6xveYEz3JnS6tzC",
        "ReFiSbuMcV8PMYcpvm9RmHDhF9HR3qyxsHZgf359NUx",
        "AEtdq4CwtuktCEUWLLpRTNPBZs6tr7BBqxkHJ1DjAttR",
        "CP6mfD4Qc5AYrboXBAQeHMYj5x1UnYksDXRjG7DMkHH7",
        "2g2QU1NDRax6i2mKzRwgRfdBFoDkMC6bj7Zp5Q3i8sCq",
        "6W8yrMwtDU5G6ErazhZHfLjqZV8cMvajpSRGYgrZ3d4v",
        "NeodymeDFipD7eA1ShrLJAZTBdHWcFsDB9YkoHshZNk",
        "DFQjGLCKVydxt8yysCGz54mCEWn9kfFiWGuJV9n1fgyP",
        "4PsiLMyoUQ7QRn1FFiFCvej4hsUTFzfvJnyN4bj1tmSN",
        "HxRrsnbc6K8CdEo3LCTrSUkFaDDxv9BdJsTDzBKnUVWH",
        "BxFf75Vtzro2Hy3coFHKxFMZo5au8W7J8BmLC3gCMotU",
        "DHoZJqvvMGvAXw85Lmsob7YwQzFVisYg8HY4rt5BAj6M",
        "6cvBCfFXugkTqgSFVPvzhoWaLbhHWvZfSsZadWP5rryR",
        "3VZHxnkK1A3HYeWYaqgMebHnc2acgLzRiXYwTNm3ooYM",
        "chrtyiAw8suFRvS7rTcfgcDyNu49bGPNZ2fjSPzNPFr",
        "6SF5cmEXFFEmnFd5BwM4J6NkZhh3WfPkgmqdoAGjLLPX",
        "capyZmRCkNE34ifDrRdfLtDB4Fi58rtLa94H9nU5z7n",
        "nateBZg7oHVPLB2samBLkKvfzedU3ALZBexMFPMKjn1",
        "gfR2VCrsVcm1gF2teasQpP6BdX99mVVFhEQck3UhTNC",
        "9Diao4uo6NpeMud7t5wvGnJ3WxDM7iaYxkGtJM36T4dy",
        "3Qvmhayko5Yn3sSXDsHsMzS8QjdU4CshQF2y6L276kgi",
        "JEJzKYzyYJJjtn6Yb1P7r6YV75TdSNmmJT49sgDoHvmk",
        "StepeLdhJ2znRjHcZdjwMWsC4nTRURNKQY8Nca82LJp",
        "J4ZJRgLhBcwFQpesq9jSWhian4czdVFJ2eo3WvhomQNq",
        "J21SMPFJEY9ExCDPiSJQXN23PVSeoQe3LnKD7QcP3bgP",
        "sTach38ebT8jnGH8i2D1g8NDAS6An19whVMnSSWPXt4",
        "4jEHuQZTNTRYAhxRYEjV3HJ1b4wqdQjnBRdPzFWzkCft",
        "DSzLJLUQD55sxaCsJBHLFSV1SYngMmT7oY8rLpFhyGgb",
        "4tuMshQNpAFpy1YtEHnSsE5EPN1mAT8FevWvn2UPJHNM",
        "7miZ2ZoXwS3YDzBRCbWcEtNVyuxk8WbbcyQwq7i5btvZ",
        "GMpKrAwQ9oa4sJqEYQezLr8Z2TUAU72tXD4iMyfoJjbh",
        "A11pGbZDE8fPNZgiqDjoST6v3QMdhzZ3r8W5YahCKtS5",
        "ZoDVQ5zCgFyVm2Y6vHhZ6boQEZNV6sMVnefev4M2Bes",
        "Ay5AcULBRJznGEEaGm2mWziRbefETRjdfZ1kwsoXS9u",
        "PineDoC593nrX16W8ZLWfF5Evb6otv7fRfZMLjPAHe3",
        "6x9uLhegx488uA3dPoq8DWHS488K4FsEqeeMXeW7kQPx",
        "BZZFpWeasotFsxhwiwTz37BqtV5BjQtfkrVxz73zqQV",
        "MARvNLH6rCLroQEGr8fWNxygJ7fHJRCfykRk9DqzwVn",
        "oPaLTmyvoUhW26QCMwLA5JNUeBYy72PDpFoXQF8SeX4"
    ]

    def __init__(self, rpc_url: str, fetch_interval_ms: int = 600000):
        self.rpc_url = rpc_url
        self.fetch_interval_ms = fetch_interval_ms
        self.leader_schedule: Dict[int, str] = {}  # slot -> validator pubkey
        self.last_fetch = 0
        self.running = False
        self.session: Optional[aiohttp.ClientSession] = None

    async def start(self, session: aiohttp.ClientSession):
        """Start the leader tracker."""
        self.session = session
        self.running = True
        asyncio.create_task(self._fetch_loop())

    async def stop(self):
        """Stop the leader tracker."""
        self.running = False

    async def _fetch_loop(self):
        """Fetch leader schedule periodically."""
        while self.running:
            try:
                await self._fetch_leader_schedule()
                await asyncio.sleep(self.fetch_interval_ms / 1000)
            except Exception as e:
                logger.error(f"Error in leader fetch loop: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    async def _fetch_leader_schedule(self):
        """Fetch upcoming slot leaders."""
        try:
            # Get current slot
            current_slot_payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getSlot",
                "params": []
            }
            async with self.session.post(self.rpc_url, json=current_slot_payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get current slot: {resp.status}")
                data = await resp.json()
                current_slot = data["result"]

            # Fetch leaders for next 5000 slots
            leaders_payload = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "getSlotLeaders",
                "params": [current_slot, 5000]
            }
            async with self.session.post(self.rpc_url, json=leaders_payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get slot leaders: {resp.status}")
                data = await resp.json()
                leaders = data["result"]

            # Update cache
            self.leader_schedule = {}
            for i, leader_pubkey in enumerate(leaders):
                slot = current_slot + i
                self.leader_schedule[slot] = leader_pubkey

            self.last_fetch = asyncio.get_event_loop().time()
            logger.info(f"✅ Updated leader schedule for {len(leaders)} slots starting from {current_slot}")

        except Exception as e:
            logger.error(f"Failed to fetch leader schedule: {e}")

    def get_leader_for_slot(self, slot: int) -> Optional[str]:
        """Get the validator pubkey for a given slot."""
        return self.leader_schedule.get(slot)

    def is_jito_slot(self, slot: int) -> bool:
        """Check if the slot leader is Jito-compatible."""
        leader = self.get_leader_for_slot(slot)
        if not leader:
            return False  # Unknown, assume not Jito

        # Check if leader is in Jito validators list
        return leader in self.JITO_VALIDATOR_VOTES

    def get_current_slot_leader(self, current_slot: int) -> Optional[str]:
        """Get the leader for the current slot."""
        return self.get_leader_for_slot(current_slot)

    async def calculate_aggressive_priority_fee(self, session: aiohttp.ClientSession, rpc_url: str, max_fee_sol: float) -> float:
        """Calculate aggressive priority fee for non-Jito slots."""
        try:
            # Get recent prioritization fees
            payload = {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "getRecentPrioritizationFees",
                "params": [["11111111111111111111111111111112"]]  # System program
            }
            async with session.post(rpc_url, json=payload) as resp:
                if resp.status != 200:
                    raise Exception(f"Failed to get prioritization fees: {resp.status}")
                data = await resp.json()

            fees = data["result"]
            if not fees:
                return 0.0

            # Get 90th percentile of last 5 blocks
            recent_fees = [fee["prioritizationFee"] for fee in fees[:5]]  # Last 5
            if not recent_fees:
                return 0.0

            sorted_fees = sorted(recent_fees)
            index = int(len(sorted_fees) * 0.9)  # 90th percentile
            base_fee = sorted_fees[min(index, len(sorted_fees) - 1)]

            # Add 20% buffer
            aggressive_fee = base_fee * 1.2

            # Convert lamports to SOL
            aggressive_fee_sol = aggressive_fee / 1_000_000_000

            # Cap at max_fee_sol
            return min(aggressive_fee_sol, max_fee_sol)

        except Exception as e:
            logger.error(f"Failed to calculate priority fee: {e}")
            return 0.0

    def is_jito_imminent(self) -> bool:
        """Fix 69: Return True if any Jito leader in next 10 slots."""
        # Simplified: assume schedule cached in self.current_schedule
        schedule = getattr(self, 'current_schedule', [])
        return any(vote in self.JITO_VALIDATOR_VOTES for vote in schedule[:10])