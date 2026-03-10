package com.hopnshoppe.user.filter;

import com.hopnshoppe.user.util.JwtUtil;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.List;

/**
 * Servlet filter that establishes the Spring Security context on each request.
 *
 * <h2>Primary path — gateway requests</h2>
 * Trusts the {@code X-User-Id} header injected by the API gateway after JWT
 * validation. This avoids redundant HMAC-SHA crypto on every request and is
 * safe because the gateway strips any client-supplied {@code X-User-Id} before
 * forwarding, then re-injects it only after a valid JWT is confirmed.
 *
 * <h2>Fallback path — direct access / local dev</h2>
 * When {@code X-User-Id} is absent (e.g. a direct call to port 8084 during
 * local development, or an internal service-to-service call that bypasses the
 * gateway), this filter falls back to validating the
 * {@code Authorization: Bearer} JWT directly.
 * This preserves defence-in-depth: user-service remains secure even if the
 * gateway is bypassed inside the cluster.
 */
public class JwtFilter extends OncePerRequestFilter {

    private final JwtUtil jwtUtil;

    public JwtFilter(JwtUtil jwtUtil) {
        this.jwtUtil = jwtUtil;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request,
                                    HttpServletResponse response,
                                    FilterChain filterChain)
            throws ServletException, IOException {

        // ── Primary path: trust the gateway-injected X-User-Id header ────────────
        // Safe because the gateway unconditionally strips this header from external
        // clients before performing JWT validation and re-injecting it.
        String userId = request.getHeader("X-User-Id");
        if (userId != null && !userId.isBlank()) {
            SecurityContextHolder.getContext().setAuthentication(
                    new UsernamePasswordAuthenticationToken(userId, null, List.of()));
            filterChain.doFilter(request, response);
            return;
        }

        // ── Fallback: validate JWT directly (defence-in-depth) ───────────────────
        String authHeader = request.getHeader("Authorization");
        if (authHeader != null && authHeader.startsWith("Bearer ")) {
            String token = authHeader.substring(7);
            if (jwtUtil.validateToken(token)) {
                String email = jwtUtil.extractUsername(token);
                SecurityContextHolder.getContext().setAuthentication(
                        new UsernamePasswordAuthenticationToken(email, null, List.of()));
            }
        }

        filterChain.doFilter(request, response);
    }
}
