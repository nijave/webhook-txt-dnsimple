import json
import logging
import os
import time
import typing

import dns, dns.resolver, dns.rdata
import requests
from flask import Flask, abort, request, jsonify

AUTHENTICATION_MAP = json.loads(os.environ["AUTHENTICATION"])
DNSIMPLE_ACCOUNT_ID = os.environ["DNSIMPLE_ACCOUNT_ID"]
DNSIMPLE_API_KEY = os.environ["DNSIMPLE_API_KEY"]

DEFAULT_RECORD_TTL = 60

app = Flask("webhook-txt-dnsimple")

gunicorn_logger = logging.getLogger("gunicorn.error")
if len(gunicorn_logger.handlers) > 0:
    app.logger.handlers = gunicorn_logger.handlers
    print("using gunciorn logger with level", gunicorn_logger.level)
    app.logger.setLevel(gunicorn_logger.level)
else:
    logging.basicConfig(level=logging.INFO)


def _validate() -> (str, typing.List[dns.rdata.Rdata]):
    app.logger.debug(
        json.dumps(
            {k: v for k, v in request.headers.items() if k not in ("Authorization",)}
        )
    )

    if request.authorization is None:
        abort(401)
    if request.authorization.type.lower() != "basic":
        abort(401)

    domain = request.authorization.parameters["username"]
    token = request.authorization.parameters["password"]

    app.logger.info('request from "%s" with token "%s..."', domain, token[0:4])

    if domain != request.view_args.get("hostname"):
        abort(401)

    if AUTHENTICATION_MAP.get(domain) != token:
        abort(401)


class DnsimpleProcessor:
    """A class for managing dnsimple interactions"""

    def __init__(
        self,
        hostname: str,
        account_id: str = DNSIMPLE_ACCOUNT_ID,
        api_key: str = DNSIMPLE_API_KEY,
    ):
        self.logger = app.logger

        self.hostname = hostname
        self._zone_name = self._find_zone(hostname).rstrip(".")
        self._zone_id = None

        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        self.base_url = f"https://api.dnsimple.com/v2/{account_id}"

        self._lookup_zone_id()

        self.record_name = (
            dns.name.from_text(self.hostname)
            .relativize(dns.name.from_text(self._zone_name))
            .to_text()
        )

    def _find_zone(self, domain, max_time: float = 15.0):
        dns_name = dns.name.from_text(domain)
        start_time = time.time()

        while True:
            if len(dns_name.labels) <= 2:
                break

            if time.time() - start_time >= max_time:
                self.logger.warning("timeout looking up soa")
                raise AttributeError("timed out looking up soa")
            try:
                dns.resolver.resolve(dns_name, "soa", lifetime=0.75)
            except (
                dns.resolver.NoAnswer,
                dns.resolver.NoNameservers,
                dns.resolver.NXDOMAIN,
            ):
                dns_name = dns_name.parent()
                continue
            except dns.resolver.LifetimeTimeout:
                self.logger.info(
                    "timeout attempting to lookup domain soa record. retrying"
                )
                time.sleep(0.25)
                continue

            break

        return dns_name.to_text()

    def _lookup_zone_id(self):
        page = 1
        while True:
            response = self.session.get(
                f"{self.base_url}/zones",
                params={"per_page": 100, "page": page},
            )

            for zone in response.json()["data"]:
                if zone["name"] == self._zone_name:
                    self._zone_id = zone["id"]
                    break

            if response.json()["pagination"]["total_pages"] > page:
                page += 1
            else:
                break

        if self._zone_id is None:
            raise ValueError("couldn't find zone")

    def find_records(
        self,
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        # TODO this doesn't handle pagination but there should only be up to 2 records...
        response = self.session.get(
            f"{self.base_url}/zones/{self._zone_id}/records",
            params={
                "name": self.record_name,
                "type": "TXT",
            },
        )
        total_pages = response.json()["pagination"]["total_pages"]
        if total_pages != 1:
            self.logger.warning(
                "found %d pages of dns records. results are unpredictable", total_pages
            )

        return response.json()["data"]

    def create_record(self, contents: str) -> None:
        url = f"{self.base_url}/zones/{self._zone_id}/records"
        payload = {
            "name": self.hostname,
            "type": "TXT",
            "content": contents,
            "ttl": DEFAULT_RECORD_TTL,
        }
        success_code = 201

        self.logger.info("creating new record in zone %d", self._zone_id)

        response = self.session.post(
            url,
            json=payload,
        )

        if response.status_code != success_code:
            self.logger.error(
                "failed to create/update record: status_code=%d response=%s",
                response.status_code,
                response.text,
            )
            raise ValueError("failed to create/update dnsimple record")

        return True

    def delete_records(self):
        existing_records = self.find_records()
        for record in existing_records:
            app.logger.info("deleting record id=%s", record["id"])
            url = f"{self.base_url}/zones/{self._zone_id}/records/{record['id']}"
            response = self.session.delete(url)
            if response.status_code != 204:
                app.logger.error("failed to delete record id=%s", record["id"])
                app.logger.warning(
                    "response content=%s", json.dumps(response.content())
                )
                raise ValueError(f"failed to delete record {record['id']}")


@app.route("/txt/<hostname>", methods=["GET", "DELETE", "POST"])
def _(hostname: str):
    _validate()

    processor = DnsimpleProcessor(hostname)

    if request.method == "GET":
        records = processor.find_records()
        return jsonify(records)
    elif request.method == "POST":
        app.logger.info("deleting any existing records")
        processor.delete_records()
        content = request.json.get("content")
        if not content:
            abort(400)
        app.logger.info("creating new record")
        processor.create_record(content)
        return jsonify({"status": "ok"})
    elif request.method == "DELETE":
        processor.delete_records()
        return jsonify({"status": "ok"})

    abort(400)


if __name__ == "__main__":
    app.run(host="localhost")
