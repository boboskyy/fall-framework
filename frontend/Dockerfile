# Pre-built Next.js standalone runner
# Build locally with `npm run build` (requires output: 'standalone' in next.config.js)
# Then place .next/, public/ in this directory before building the image.
FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

# standalone output nests under project dir name (frontend/)
COPY --chown=nextjs:nodejs .next/standalone/frontend ./
COPY --chown=nextjs:nodejs .next/static ./.next/static
COPY --chown=nextjs:nodejs public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
