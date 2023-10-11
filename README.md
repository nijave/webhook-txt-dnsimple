# webhook-dyn-dnsimple
A webhook for processing dyndns/no-ip like requests and running against dnsimple.com.

## Doesn't this exist?
I don't think so. I found https://ddns.horse/, but this webhook is designed to prevent clients from getting powerful dnsimple.com api keys. The webhook gets the powerful key and clients get their own hostname-scoped keys.

## Usage
```bash
docker run -d --restart unless-stopped \
	-e 'AUTHENTICATION={"my-home.dyndns.com":"some-fairly-long-secret-key"}' \
	-e "DNSIMPLE_ACCOUNT_ID=1234" \
	-e "DNSIMPLE_API_KEY=dnsimple_abc123" \
	--name webhook-dyn-dnsimple \
	ghcr.io/nijave/webhook-dyn-dnsimple
```

Config:
- `AUTHENTICATION` should be a json object of `hostname` to `per client api key` mappings.
- `DNSIMPLE_ACCOUNT_ID` numeric dnsimple account id. It's in the URI if you click `Account` on dnsimple.com
- `DNSIMPLE_API_KEY` a key from `Account` > `Access Tokens` on dnsimple.com

### Api key logging
**NOTE** this logs the first 4 characters of client api keys for debugging purposes. You should ensure your client api keys are sufficiently long that knowing the first 4 characters doesn't compromise security (recommend 20+ characters).

## Client config
See https://ddns.horse/ (you'll need a hostname that routes to the Docker container).

### opnsense
- `Service` Custom
- `Protocol` DynDNS 2
- `Server` My hostname that points at the Docker container. I use nginx->Traefik->Docker and terminate TLS at nginx.
- `Username` your dynamic dns hostname
- `Password` the corresponding string in `AUTHENTICATION` map for `Username`
- `Hostname(s)` must be the same as `Username`, the dynamic dns hostname you want updated