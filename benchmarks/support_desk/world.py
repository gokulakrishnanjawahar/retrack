"""A small, deterministic customer-support world with gotchas a naive agent hits.

Gotchas (what memory should teach):
  * issue_refund fails unless check_delivery was called for the order first;
  * issue_refund needs the amount in paise, but lookup_order reports rupees;
  * update_address needs the PIN code in its own `pin_code` argument.
Every task can be verified exactly, so outcomes are reported as test signals.
"""

import random
from dataclasses import dataclass, field
from typing import Any

from langchain_core.tools import StructuredTool

TOOL_VERSIONS = {"orders_api": "v3", "refunds_api": "v2", "address_api": "v1"}
TOOL_NAMES = ["lookup_order", "check_delivery", "issue_refund", "update_address"]


@dataclass(frozen=True)
class Task:
    family: str  # "refund" or "address"
    text: str
    order_id: str
    new_address: str = ""
    pin_code: str = ""


@dataclass
class Order:
    order_id: str
    status: str
    amount_paise: int
    address: str = ""
    pin_code: str = ""


@dataclass
class World:
    """One episode's state. Create a fresh World (same seed) per attempt."""

    seed: int
    orders: dict[str, Order] = field(default_factory=dict)
    delivery_checked: set[str] = field(default_factory=set)
    refunds: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        rng = random.Random(self.seed)
        for _ in range(40):
            order_id = str(rng.randint(10000, 99999))
            self.orders[order_id] = Order(
                order_id,
                rng.choice(["delivered", "delivered", "shipped"]),
                rng.randint(199, 9999) * 100 + rng.choice([0, 50, 99]),
            )

    # Tools ------------------------------------------------------------------------

    def lookup_order(self, order_id: str) -> dict[str, Any]:
        """Look up an order: its status and total amount in rupees."""
        order = self.orders.get(order_id)
        if order is None:
            return {"error": "order not found"}
        return {
            "order_id": order_id,
            "status": order.status,
            "amount_rupees": order.amount_paise / 100,
        }

    def check_delivery(self, order_id: str) -> dict[str, Any]:
        """Check whether an order was delivered."""
        order = self.orders.get(order_id)
        if order is None:
            return {"error": "order not found"}
        self.delivery_checked.add(order_id)
        return {"order_id": order_id, "delivered": order.status == "delivered"}

    def issue_refund(self, order_id: str, amount_paise: int) -> dict[str, Any]:
        """Refund an order. amount_paise is the refund amount in paise."""
        order = self.orders.get(order_id)
        if order is None:
            return {"error": "order not found"}
        if order_id not in self.delivery_checked:
            return {"error": "delivery not verified: call check_delivery first", "status": 409}
        if amount_paise != order.amount_paise:
            return {"error": "amount_paise must equal the order total in paise", "status": 422}
        self.refunds[order_id] = amount_paise
        return {"refund_id": f"rf_{order_id}", "status": 200}

    def update_address(self, order_id: str, address: str, pin_code: str = "") -> dict[str, Any]:
        """Change the delivery address of an order."""
        order = self.orders.get(order_id)
        if order is None:
            return {"error": "order not found"}
        if not pin_code:
            return {"error": "pin_code is required as a separate argument", "status": 422}
        order.address, order.pin_code = address, pin_code
        return {"order_id": order_id, "updated": True, "status": 200}

    def tools(self) -> dict[str, StructuredTool]:
        return {
            name: StructuredTool.from_function(getattr(self, name), name=name)
            for name in TOOL_NAMES
        }

    # Tasks and verification -------------------------------------------------------

    def tasks(self, count: int, offset: int = 0) -> list[Task]:
        """Alternating refund and address tasks over delivered orders, deterministic."""
        delivered = sorted(o for o, order in self.orders.items() if order.status == "delivered")
        rng = random.Random(self.seed * 7919 + offset)
        tasks = []
        for i in range(count):
            order_id = rng.choice(delivered)
            if i % 2 == 0:
                tasks.append(
                    Task(
                        "refund",
                        f"Customer says order {order_id} arrived damaged; refund it.",
                        order_id,
                    )
                )
            else:
                pin = str(rng.randint(110001, 855999))
                # Same wording each time: the $0 test embedder compares words, not meaning.
                street = f"Flat {rng.randint(1, 99)}, Block {rng.randint(1, 20)}"
                tasks.append(
                    Task(
                        "address",
                        f"Change the delivery address of order {order_id} to {street}, PIN {pin}.",
                        order_id,
                        street,
                        pin,
                    )
                )
        return tasks

    def verify(self, task: Task) -> bool:
        order = self.orders[task.order_id]
        if task.family == "refund":
            return self.refunds.get(task.order_id) == order.amount_paise
        return order.address == task.new_address and order.pin_code == task.pin_code
