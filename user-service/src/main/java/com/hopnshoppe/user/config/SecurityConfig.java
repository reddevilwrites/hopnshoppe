package com.hopnshoppe.user.config;

import com.hopnshoppe.user.filter.JwtFilter;
import com.hopnshoppe.user.util.JwtUtil;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.authentication.UsernamePasswordAuthenticationFilter;

@Configuration
public class SecurityConfig {

    private final JwtUtil jwtUtil;

    public SecurityConfig(JwtUtil jwtUtil) {
        this.jwtUtil = jwtUtil;
    }

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .csrf(csrf -> csrf.disable())
            .authorizeHttpRequests(authz -> authz
                // Public: anyone can look up a profile by ID (no sensitive data exposed)
                .requestMatchers("/users/**").permitAll()
                // Internal: service-to-service only — the gateway has no route for /internal/**
                // so external traffic can never reach these endpoints through normal flows.
                // TODO: add mTLS or a shared internal API key for production hardening.
                .requestMatchers("/internal/**").permitAll()
                // Actuator health endpoint for Docker / k8s probes
                .requestMatchers("/actuator/**").permitAll()
                // All /account/** endpoints require a valid JWT (authenticated user's own data)
                .anyRequest().authenticated()
            )
            .addFilterBefore(new JwtFilter(jwtUtil), UsernamePasswordAuthenticationFilter.class);

        return http.build();
    }
}
