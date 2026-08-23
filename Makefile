# Deploy static UI to Cloudflare Pages
# Prerequisites: npm i -g wrangler && wrangler login

.PHONY: pages-deploy pages-dev

pages-dev:
	npx wrangler pages dev web

pages-deploy:
	npx wrangler pages project create aegis-agent --production-branch=main 2>/dev/null || true
	npx wrangler pages deploy web --project-name=aegis-agent --commit-dirty=true
