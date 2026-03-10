package com.hopnshoppe.gateway.filter;

import com.hopnshoppe.gateway.config.GatewayProperties;
import com.hopnshoppe.gateway.util.JwtUtil;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.core.io.buffer.DataBuffer;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.http.server.reactive.ServerHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

import java.nio.charset.StandardCharsets;
import java.util.List;

/**
 * Global reactive filter implementing the API Gateway's Two-Tier Security Policy.
 *
 * <h2>Step 1 — Header sanitisation (all requests)</h2>
 * Strips {@code X-User-Id}, {@code X-User-Role}, {@code X-User-Email}, and
 * {@code X-Internal-Service} from every incoming request, regardless of whether
 * it targets a public or protected path. This prevents external callers from
 * spoofing the gateway-controlled identity headers.
 *
 * <h2>Step 2 — Public path bypass</h2>
 * Paths listed under {@code gateway.public-paths} skip JWT validation and are
 * forwarded with only the sanitised headers (no identity context injected).
 *
 * <h2>Step 3 — JWT validation</h2>
 * Protected paths require a valid {@code Authorization: Bearer <token>} header.
 * A 401 JSON response is returned on missing, malformed, or expired tokens.
 *
 * <h2>Step 4 — Claim extraction and trusted header injection</h2>
 * After successful validation the gateway injects three downstream headers:
 * <ul>
 *   <li>{@code X-User-Email} — JWT subject (user email); kept for backward compat</li>
 *   <li>{@code X-User-Id}    — JWT subject (email is the system's user identifier)</li>
 *   <li>{@code X-User-Role}  — first role from the {@code roles}/{@code role} claim,
 *       or {@code "ROLE_USER"} when absent</li>
 * </ul>
 * Downstream services can trust these headers and skip their own JWT parsing
 * (see {@code JwtFilter} in user-service / cart-service).
 *
 * <h2>Filter order</h2>
 * {@code -1} — runs after {@link CorrelationIdFilter} ({@code -2}) and before
 * the routing filter ({@code 1}).
 */
@Component
public class JwtAuthenticationFilter implements GlobalFilter, Ordered {

    private static final String BEARER_PREFIX    = "Bearer ";
    private static final String USER_EMAIL_HEADER = "X-User-Email";
    private static final String USER_ID_HEADER    = "X-User-Id";
    private static final String USER_ROLE_HEADER  = "X-User-Role";

    /**
     * Headers that clients must never be allowed to supply — strip unconditionally
     * on every inbound request before any routing decision is made.
     */
    private static final List<String> SPOOFABLE_HEADERS = List.of(
            "X-User-Id", "X-User-Role", "X-User-Email", "X-Internal-Service");

    private final JwtUtil jwtUtil;
    private final GatewayProperties gatewayProperties;

    public JwtAuthenticationFilter(JwtUtil jwtUtil, GatewayProperties gatewayProperties) {
        this.jwtUtil = jwtUtil;
        this.gatewayProperties = gatewayProperties;
    }

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {

        // ── Step 1: Strip spoofable identity headers from all incoming requests ──
        // Applied unconditionally (before public-path check) so that even public
        // endpoints cannot be reached with a forged identity header.
        ServerHttpRequest sanitised = exchange.getRequest().mutate()
                .headers(h -> SPOOFABLE_HEADERS.forEach(h::remove))
                .build();
        ServerWebExchange sanitisedExchange = exchange.mutate().request(sanitised).build();

        String path = sanitised.getURI().getPath();

        // ── Step 2: Public paths bypass JWT validation ────────────────────────────
        if (isPublicPath(path)) {
            return chain.filter(sanitisedExchange);
        }

        // ── Step 3: Require a Bearer token ───────────────────────────────────────
        String authHeader = sanitised.getHeaders().getFirst(HttpHeaders.AUTHORIZATION);
        if (authHeader == null || !authHeader.startsWith(BEARER_PREFIX)) {
            return reject(exchange, "Missing or malformed Authorization header — expected: Bearer <token>");
        }

        String token = authHeader.substring(BEARER_PREFIX.length());

        if (!jwtUtil.validateToken(token)) {
            return reject(exchange, "JWT token is invalid or has expired");
        }

        // ── Step 4: Extract claims and inject as trusted gateway headers ──────────
        String userEmail = jwtUtil.extractUsername(token);
        String userRole  = jwtUtil.extractRole(token);

        ServerHttpRequest enriched = sanitised.mutate()
                .header(USER_EMAIL_HEADER, userEmail)   // backward-compat alias
                .header(USER_ID_HEADER,    userEmail)   // email is this system's user ID
                .header(USER_ROLE_HEADER,  userRole)
                .build();

        return chain.filter(sanitisedExchange.mutate().request(enriched).build());
    }

    @Override
    public int getOrder() {
        // After CorrelationIdFilter (order -2), before routing filter (order 1).
        return -1;
    }

    // ── Private helpers ────────────────────────────────────────────────────────

    private boolean isPublicPath(String requestPath) {
        return gatewayProperties.getPublicPaths().stream()
                .anyMatch(requestPath::startsWith);
    }

    /**
     * Writes a JSON 401 response and short-circuits the filter chain.
     */
    private Mono<Void> reject(ServerWebExchange exchange, String message) {
        ServerHttpResponse response = exchange.getResponse();
        response.setStatusCode(HttpStatus.UNAUTHORIZED);
        response.getHeaders().setContentType(MediaType.APPLICATION_JSON);

        String body = String.format(
                "{\"status\":401,\"error\":\"Unauthorized\",\"message\":\"%s\"}", message);

        DataBuffer buffer = response.bufferFactory()
                .wrap(body.getBytes(StandardCharsets.UTF_8));

        return response.writeWith(Mono.just(buffer));
    }
}
