FROM node:20-alpine
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1

RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs

COPY package.json ./
RUN npm install --omit=dev --ignore-scripts && \
    npm rebuild sharp

COPY --chown=nextjs:nodejs .next/standalone/frontend/server.js ./
COPY --chown=nextjs:nodejs .next/standalone/frontend/.next ./.next
COPY --chown=nextjs:nodejs .next/static ./.next/static
COPY --chown=nextjs:nodejs public ./public

USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
