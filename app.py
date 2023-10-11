import ipaddress
import json
import logging
import os
import threading
import time
import typing

import dns, dns.resolver, dns.rdata
import lru
import requests
from flask import Flask, abort, request

AUTHENTICATION_MAP = json.loads(os.environ["AUTHENTICATION"])
DNSIMPLE_ACCOUNT_ID = os.environ["DNSIMPLE_ACCOUNT_ID"]
DNSIMPLE_API_KEY = os.environ["DNSIMPLE_API_KEY"]

DEFAULT_RECORD_TTL = 60

"""
Reduce requests to dnsimple and dns lookups
by keeping DnsimpleProcessors around. Saves
at least zone info
"""
CACHE = lru.LRU(10)
CACHE_LOCK = threading.Lock()

app = Flask("webhook-dyn-dnsimple")

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

    has_hostname = "hostname" in request.args

    ips = []
    # TODO fix shouldn't allow ipv4 in myipv6 and ipv6 in myip
    for ip_type in ("myip", "myipv6"):
        ip_value = request.args.get(ip_type)
        if not ip_value:
            continue
        ips.append(ipaddress.ip_address(ip_value))
    has_ip = len(ips) > 0

    if not (has_hostname and has_ip):
        app.logger.warning(
            "request missing required arguments: has_hostname=%s has_ip=%s",
            has_hostname,
            has_ip,
        )
        abort(400)

    if domain != request.args["hostname"]:
        abort(401)

    if AUTHENTICATION_MAP.get(domain) != token:
        abort(401)

    records = []
    for ip_addr in ips:
        resource_record = dns.rdata.from_text(
            rdclass=dns.rdataclass.IN,
            rdtype=dns.rdatatype.A if ip_addr.version == 4 else dns.rdatatype.AAAA,
            tok=str(ip_addr),
        )
        records.append(resource_record)

    return domain, records


class DnsimpleProcessor:
    """A class for managing dnsimple interactions"""

    def __init__(
        self,
        domain: str,
        account_id: str = DNSIMPLE_ACCOUNT_ID,
        api_key: str = DNSIMPLE_API_KEY,
    ):
        self.logger = app.logger

        self.domain = domain
        self._zone_name = self._find_zone(domain).rstrip(".")
        self._zone_id = None

        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {api_key}"})
        self.base_url = f"https://api.dnsimple.com/v2/{account_id}"

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

    def _find_existing_records(
        self, record_name: str, record_type: str
    ) -> typing.List[typing.Dict[str, typing.Any]]:
        # TODO this doesn't handle pagination but there should only be up to 2 records...
        response = self.session.get(
            f"{self.base_url}/zones/{self._zone_id}/records",
            params={
                "name": record_name,
                "type": record_type,
            },
        )
        total_pages = response.json()["pagination"]["total_pages"]
        if total_pages != 1:
            self.logger.warning(
                "found %d pages of dns records. results are unpredictable", total_pages
            )

        return response.json()["data"]

    def _update_or_create_record(
        self,
        name: str,
        existing_records: typing.Dict[str, typing.Any],
        new_record: dns.rdata.Rdata,
    ) -> None:
        for record in existing_records[1:]:
            self.logger.info(
                "deleting extra record %d for zone %d", record["id"], self._zone_id
            )
            response = self.session.delete(
                f"{self.base_url}/zones/{self._zone_id}/records/{record['id']}",
            )
            if response.status_code != 204:
                self.logger.warning(
                    "failed to delete record %d from zone %d",
                    record["id"],
                    self._zone_id,
                )

        old_record = {}
        if len(existing_records) > 0:
            old_record = existing_records[0]

        if new_record.to_text() == old_record.get("content"):
            self.logger.info(
                "skipping update since record %d in zone %d hasn't changed",
                old_record["id"],
                self._zone_id,
            )
            return

        self._create_new_record(name, new_record, old_record.get("id"))

    def _create_new_record(
        self,
        name: str,
        new_record: dns.rdata.Rdata,
        old_record_id: int = None,
    ) -> None:
        update_method = self.session.post
        url = f"{self.base_url}/zones/{self._zone_id}/records"
        payload = {
            "name": name,
            "type": new_record.rdtype.name,
            "content": new_record.to_text(),
            "ttl": DEFAULT_RECORD_TTL,
        }
        success_code = 201

        if old_record_id is not None:
            self.logger.info(
                "will patch existing record %d for zone %d",
                old_record_id,
                self._zone_id,
            )
            update_method = self.session.patch
            url += f"/{old_record_id}"
            del payload["type"]
            success_code = 200
        else:
            self.logger.info("creating new record in zone %d", self._zone_id)

        response = update_method(
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

    def update_records(self, new_records: typing.List[dns.rdata.Rdata]) -> None:
        if self._zone_id is None:
            self._lookup_zone_id()

        record_name = (
            dns.name.from_text(self.domain)
            .relativize(dns.name.from_text(self._zone_name))
            .to_text()
        )

        for record in new_records:
            existing_records = self._find_existing_records(
                record_name, record.rdtype.name
            )

            self._update_or_create_record(
                existing_records=existing_records,
                name=record_name,
                new_record=record,
            )


@app.route("/", methods=["GET", "POST"])
@app.route("/nic/update", methods=["GET", "POST"])
def _():
    domain, records = _validate()

    """
    Don't lock around creating the processor. In theory, multiple threads
    could create multiple processors concurrently. This will just keep one.
    """
    processor = None
    with CACHE_LOCK:
        if domain in CACHE:
            processor = CACHE[domain]

    if processor is None:
        processor = DnsimpleProcessor(domain)

    processor.update_records(records)

    with CACHE_LOCK:
        if domain not in CACHE:
            CACHE[domain] = processor
            app.logger.info("added %s to processor cache", domain)

    return "OK"


if __name__ == "__main__":
    app.run(host="localhost")
