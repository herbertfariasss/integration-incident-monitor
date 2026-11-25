import logging
import time

from app.database import Database
from app.services import DeliveryService


def main() -> None:
    service = DeliveryService(Database())
    while True:
        try:
            if not service.run_once():
                time.sleep(1)
        except Exception:
            logging.exception("Falha no processamento de entrega")
            time.sleep(2)


if __name__ == "__main__":
    main()
