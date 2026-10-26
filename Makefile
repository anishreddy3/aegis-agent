# Deploy static UI to Cloudflare Pages
# Prerequisites: npm i -g wrangler && wrangler login
#
# Set default API URL for judges (no manual entry):
#   AEGIS_DEFAULT_API=https://your-tunnel.trycloudflare.com make pages-deploy

.PHONY: pages-config pages-deploy pages-dev test

test:
	DEMO_MODE=true python -m pytest tests/ -q


pages-config:
	bash scripts/generate-pages-config.sh

pages-dev:
	npx wrangler pages dev web

pages-deploy: pages-config
	npx wrangler pages project create aegis-agent --production-branch=main 2>/dev/null || true
	npx wrangler pages deploy web --project-name=aegis-agent --commit-dirty=true
