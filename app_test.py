import base64
import json
import os
import re
from unittest import mock

import dns
import pytest
import responses

HOSTNAME = "example.com"
API_KEY = "abc"
TXT_VALUE = "abc123"

os.environ["AUTHENTICATION"] = json.dumps(
    {
        HOSTNAME: API_KEY,
        f"test.{HOSTNAME}": API_KEY,
    }
)
os.environ["DNSIMPLE_ACCOUNT_ID"] = "123"
os.environ["DNSIMPLE_API_KEY"] = "secret"

from app import app

ZONE_RESPONSE = responses.Response(
    method="GET",
    url=f"https://api.dnsimple.com/v2/{os.environ['DNSIMPLE_ACCOUNT_ID']}/zones",
    json={
        "data": [
            {
                "id": 1,
                "account_id": os.environ["DNSIMPLE_ACCOUNT_ID"],
                "name": HOSTNAME,
                "reverse": False,
                "secondary": False,
                "last_transferred_at": None,
                "active": True,
                "created_at": "2015-04-23T07:40:03Z",
                "updated_at": "2015-04-23T07:40:03Z",
            },
        ],
        "pagination": {"total_pages": 1},
    },
)

RECORDS_RESPONSE = [
    responses.Response(
        method="GET",
        url=f"https://api.dnsimple.com/v2/{os.environ['DNSIMPLE_ACCOUNT_ID']}/zones/1/records",
        match=[
            responses.matchers.query_param_matcher(
                {
                    "name": "@",
                    "type": "TXT",
                }
            )
        ],
        json={"data": [], "pagination": {"total_pages": 1}},
    ),
    responses.Response(
        method="GET",
        url=f"https://api.dnsimple.com/v2/{os.environ['DNSIMPLE_ACCOUNT_ID']}/zones/1/records",
        match=[
            responses.matchers.query_param_matcher(
                {
                    "name": "@",
                    "type": "TXT",
                }
            )
        ],
        json={
            "data": [
                {
                    "id": 1,
                    "zone_id": "example.com",
                    "parent_id": None,
                    "name": "",
                    "content": TXT_VALUE,
                    "ttl": 3600,
                    "priority": None,
                    "type": "TXT",
                    "regions": ["global"],
                    "system_record": True,
                    "created_at": "2016-03-22T10:20:53Z",
                    "updated_at": "2016-10-05T09:26:38Z",
                },
            ],
            "pagination": {"total_pages": 1},
        },
    ),
    responses.Response(
        method="GET",
        url=f"https://api.dnsimple.com/v2/{os.environ['DNSIMPLE_ACCOUNT_ID']}/zones/1/records",
        match=[
            responses.matchers.query_param_matcher(
                {
                    "name": "test",
                    "type": "TXT",
                }
            )
        ],
        json={
            "data": [
                {
                    "id": 1,
                    "zone_id": "example.com",
                    "parent_id": None,
                    "name": "test",
                    "content": TXT_VALUE,
                    "ttl": 3600,
                    "priority": None,
                    "type": "TXT",
                    "regions": ["global"],
                    "system_record": True,
                    "created_at": "2016-03-22T10:20:53Z",
                    "updated_at": "2016-10-05T09:26:38Z",
                },
            ],
            "pagination": {"total_pages": 1},
        },
    ),
]

RECORD_CREATE = responses.Response(
    method="POST",
    url=f"https://api.dnsimple.com/v2/{os.environ['DNSIMPLE_ACCOUNT_ID']}/zones/1/records",
    status=201,
    json={
        "data": {
            "id": 1,
            "zone_id": "example.com",
            "parent_id": None,
            "name": "",
            "content": TXT_VALUE,
            "ttl": 60,
            "priority": None,
            "type": "TXT",
            "system_record": None,
            "regions": ["global"],
            "created_at": "2016-01-07T17:45:13Z",
            "updated_at": "2016-01-07T17:45:13Z",
        }
    },
)

RECORD_DELETE = responses.Response(
    method="DELETE",
    url=f"https://api.dnsimple.com/v2/{os.environ['DNSIMPLE_ACCOUNT_ID']}/zones/1/records/1",
    status=204,
)

DNS_ANSWER = mock.MagicMock(
    return_value=dns.resolver.Answer(
        qname=dns.name.from_text(HOSTNAME),
        rdtype=dns.rdatatype.SOA,
        rdclass=dns.rdataclass.IN,
        response=dns.message.from_text(
            """id 56390
opcode QUERY
rcode NOERROR
flags QR RD RA
edns 0
payload 65494
;QUESTION
example.com. IN SOA
;ANSWER
example.com. 2031 IN SOA ns.icann.org. noc.dns.icann.org. 2022091379 7200 3600 1209600 3600
;AUTHORITY
;ADDITIONAL"""
        ),
    )
)


def auth_header(hostname, api_key=API_KEY):
    return {
        "Authorization": "Basic %s"
        % base64.b64encode(f"{hostname}:{api_key}".encode("ascii")).decode()
    }


@pytest.fixture()
def client():
    return app.test_client()


@mock.patch("app.dns.resolver.resolve", new=DNS_ANSWER)
@responses.activate
@pytest.mark.parametrize(
    "response_number,expected_results",
    [
        (0, 0),
        (1, 1),
    ],
)
def test_find_records(client, response_number, expected_results):
    responses.add(ZONE_RESPONSE)
    responses.add(RECORDS_RESPONSE[response_number])

    response = client.get(
        f"/txt/{HOSTNAME}",
        headers=auth_header(HOSTNAME),
    )

    assert response.status_code == 200
    assert len(response.json) == expected_results


@responses.activate
def test_find_records_recursive_zone(client):
    resolver = mock.Mock(
        side_effect=[
            dns.resolver.NXDOMAIN(
                "The DNS query name does not exist: test.example.com."
            ),
            DNS_ANSWER,
        ]
    )

    responses.add(ZONE_RESPONSE)
    responses.add(RECORDS_RESPONSE[0])
    responses.add(RECORDS_RESPONSE[2])

    with mock.patch("app.dns.resolver.resolve", new=resolver):
        response = client.get(
            f"/txt/test.{HOSTNAME}",
            headers=auth_header(f"test.{HOSTNAME}"),
        )

    assert response.status_code == 200
    assert resolver.call_count == 2


@mock.patch("app.dns.resolver.resolve", new=DNS_ANSWER)
@responses.activate
def test_create_record(client):
    responses.add(ZONE_RESPONSE)
    responses.add(RECORDS_RESPONSE[0])
    create_response = responses.add(RECORD_CREATE)
    txt_record = "abc123"

    response = client.post(
        f"/txt/example.com",
        headers=auth_header(HOSTNAME),
        json={"content": txt_record},
    )

    assert response.status_code == 200
    assert create_response.call_count == 1


@responses.activate
def test_delete_record(client):
    responses.add(ZONE_RESPONSE)
    responses.add(RECORDS_RESPONSE[1])
    delete_response = responses.add(RECORD_DELETE)

    response = client.delete(
        f"/txt/example.com",
        headers=auth_header(HOSTNAME),
    )

    assert response.status_code == 200
    assert delete_response.call_count == 1
