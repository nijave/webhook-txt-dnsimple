# webhook-txt-dnsimple
A webhook for processing txt record requests and running against dnsimple.com. Similar to https://github.com/nijave/webhook-dyn-dnsimple

## Usage
```bash
docker run -d --restart unless-stopped \
	-e 'AUTHENTICATION={"my-home.dyndns.com":"some-fairly-long-secret-key"}' \
	-e "DNSIMPLE_ACCOUNT_ID=1234" \
	-e "DNSIMPLE_API_KEY=dnsimple_abc123" \
	--name webhook-txt-dnsimple \
	ghcr.io/nijave/webhook-txt-dnsimple
```

Config:
- `AUTHENTICATION` should be a json object of `hostname` to `per client api key` mappings.
- `DNSIMPLE_ACCOUNT_ID` numeric dnsimple account id. It's in the URI if you click `Account` on dnsimple.com
- `DNSIMPLE_API_KEY` a key from `Account` > `Access Tokens` on dnsimple.com

### Api key logging
**NOTE** this logs the first 4 characters of client api keys for debugging purposes. You should ensure your client api keys are sufficiently long that knowing the first 4 characters doesn't compromise security (recommend 20+ characters).