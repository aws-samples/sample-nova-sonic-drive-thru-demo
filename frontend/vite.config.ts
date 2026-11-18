// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: MIT-0

/// <reference types="vitest/config" />
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

import path from 'path'
import fs from 'fs'
import type { Plugin } from 'vite'

// Serve data/images/ at /images/ during local dev
function serveDataImages(): Plugin {
  return {
    name: 'serve-data-images',
    configureServer(server) {
      server.middlewares.use('/images', (req, res, next) => {
        const filePath = path.resolve(__dirname, '../data/images', req.url!.slice(1) || '')
        if (fs.existsSync(filePath)) {
          const ext = path.extname(filePath)
          const mime = ext === '.svg' ? 'image/svg+xml' : ext === '.jpg' ? 'image/jpeg' : 'application/octet-stream'
          res.setHeader('Content-Type', mime)
          fs.createReadStream(filePath).pipe(res)
        } else {
          next()
        }
      })
    },
  }
}

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), serveDataImages()],
  build: {
    rolldownOptions: {
      output: {
        // React and Amplify are most of the bundle and change far less often than the app,
        // so they get their own chunks: after a deploy that only changes app code, browsers
        // keep the libraries they already have cached.
        codeSplitting: {
          groups: [
            { name: 'amplify', test: /node_modules[\\/](@aws-amplify|aws-amplify|@aws-crypto|@aws-sdk|@smithy|xstate|@xstate|lodash|qrcode)/, priority: 2 },
            { name: 'react', test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/, priority: 1 },
          ],
        },
      },
    },
    // The Amplify chunk is ~600 kB (~160 kB gzipped) on its own; it is cached across deploys
    chunkSizeWarningLimit: 700,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: './src/test/setup.ts',
  },
})
