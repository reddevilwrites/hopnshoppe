package com.hopnshoppe.gateway.util;

import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.nio.charset.StandardCharsets;
import java.security.Key;
import java.util.List;

/**
 * Stateless JWT validator for the API Gateway.
 *
 * <p>The gateway only validates and reads tokens — it never issues them.
 * Token issuance is the exclusive responsibility of auth-service.
 *
 * <p>The signing key MUST match the {@code JWT_SECRET} used by auth-service.
 * Both services read the secret from the same environment variable so they
 * stay in sync without any coordination.
 */
@Component
public class JwtUtil {

    private final Key signingKey;

    public JwtUtil(@Value("${jwt.secret}") String secret) {
        // Keys.hmacShaKeyFor requires at least 32 bytes for HS256.
        this.signingKey = Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    /**
     * Returns {@code true} if the token signature is valid and it has not expired.
     * All JJWT exceptions (expired, malformed, unsupported, invalid signature)
     * are caught and mapped to {@code false}.
     */
    public boolean validateToken(String token) {
        try {
            Jwts.parserBuilder()
                    .setSigningKey(signingKey)
                    .build()
                    .parseClaimsJws(token);
            return true;
        } catch (JwtException | IllegalArgumentException e) {
            return false;
        }
    }

    /**
     * Extracts the subject (user email) from a token that has already been
     * validated with {@link #validateToken(String)}.
     */
    public String extractUsername(String token) {
        return Jwts.parserBuilder()
                .setSigningKey(signingKey)
                .build()
                .parseClaimsJws(token)
                .getBody()
                .getSubject();
    }

    /**
     * Extracts the first role from the JWT {@code roles} claim (list) or the
     * scalar {@code role} claim. Returns {@code "ROLE_USER"} when neither claim
     * is present — this keeps the system functional as roles are added
     * incrementally to the auth-service token payload.
     */
    public String extractRole(String token) {
        try {
            Claims claims = Jwts.parserBuilder()
                    .setSigningKey(signingKey)
                    .build()
                    .parseClaimsJws(token)
                    .getBody();

            @SuppressWarnings("unchecked")
            List<String> roles = claims.get("roles", List.class);
            if (roles != null && !roles.isEmpty()) {
                return roles.get(0);
            }
            String role = claims.get("role", String.class);
            if (role != null && !role.isBlank()) {
                return role;
            }
        } catch (JwtException e) {
            // fall through to default
        }
        return "ROLE_USER";
    }
}
