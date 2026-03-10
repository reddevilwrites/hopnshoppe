package com.hopnshoppe.gateway.filter;

import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.util.UUID;

/**
 * Global reactive filter that guarantees every request carries an {@code X-Correlation-Id}.
 *
 * <h2>Behaviour</h2>
 * <ul>
 *   <li>If the incoming request already contains {@code X-Correlation-Id}, the existing
 *       value is forwarded unchanged (allows distributed traces to propagate from
 *       upstream callers or CDN edge nodes).</li>
 *   <li>If the header is absent or blank, a new random UUID is generated and injected
 *       into both the downstream request and the outgoing response so clients can
 *       correlate their request with server-side logs.</li>
 * </ul>
 *
 * <h2>Filter order</h2>
 * {@code -2} — runs before {@link JwtAuthenticationFilter} ({@code -1}) so that the
 * correlation ID is available to every subsequent filter and downstream service.
 */
@Component
public class CorrelationIdFilter implements GlobalFilter, Ordered {

    static final String CORRELATION_ID_HEADER = "X-Correlation-Id";

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        String correlationId = exchange.getRequest().getHeaders().getFirst(CORRELATION_ID_HEADER);

        if (correlationId == null || correlationId.isBlank()) {
            correlationId = UUID.randomUUID().toString();
        }

        final String finalCorrelationId = correlationId;

        ServerHttpRequest mutatedRequest = exchange.getRequest().mutate()
                .header(CORRELATION_ID_HEADER, finalCorrelationId)
                .build();

        ServerWebExchange mutatedExchange = exchange.mutate().request(mutatedRequest).build();

        // Echo the correlation ID on the response so clients can match
        // their request to server-side traces.
        mutatedExchange.getResponse().getHeaders().set(CORRELATION_ID_HEADER, finalCorrelationId);

        return chain.filter(mutatedExchange);
    }

    @Override
    public int getOrder() {
        return -2;
    }
}
