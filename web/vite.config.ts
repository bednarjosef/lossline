import { svelte } from '@sveltejs/vite-plugin-svelte'
import { defineConfig, type Plugin } from 'vite'

// The public URL the app is served from, e.g. https://you.github.io/lossline/.
// When set, the build emits an OAuth client metadata document so "Sign in with
// Hugging Face" works without registering an app: the document's own URL is the
// client ID. Without it, the app offers token sign-in only.
const siteUrl = process.env.LOSSLINE_SITE_URL?.replace(/\/?$/, '/')

function oauthClient(): Plugin {
  return {
    name: 'lossline-oauth-client',
    generateBundle() {
      if (!siteUrl) return
      this.emitFile({
        type: 'asset',
        fileName: 'oauth-client.json',
        source: JSON.stringify(
          {
            client_id: `${siteUrl}oauth-client.json`,
            client_name: 'lossline',
            client_uri: siteUrl,
            redirect_uris: [siteUrl],
            token_endpoint_auth_method: 'none',
          },
          null,
          2,
        ),
      })
    },
  }
}

export default defineConfig({
  base: './',
  plugins: [svelte(), oauthClient()],
  define: {
    __SITE_URL__: JSON.stringify(siteUrl ?? ''),
  },
  server: { port: 5190 },
  preview: { port: 5191 },
})
