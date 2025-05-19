package com.wknd.spring.client.config_client.filter;

import java.io.IOException;
import java.util.List;

import org.springframework.security.authentication.UsernamePasswordAuthenticationToken;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.web.filter.OncePerRequestFilter;

import com.wknd.spring.client.config_client.util.JwtUtil;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

public class JwtFilter extends OncePerRequestFilter{

    private final JwtUtil jwtUtil;
    public JwtFilter(JwtUtil jwtUtil){
        this.jwtUtil = jwtUtil;
    }

    @Override
    protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain filterChain)
            throws ServletException, IOException {
        String authHeader = request.getHeader("Authorization");

        if(authHeader != null && authHeader.startsWith("Bearer ")){
            String jwt = authHeader.substring(7);
            if(jwtUtil.validationToken(jwt)){
                String userName = jwtUtil.extractUsername(jwt);
                System.out.println("User Name inside the Jwt Filter: " + userName);

                UsernamePasswordAuthenticationToken auth = new UsernamePasswordAuthenticationToken(userName, null, List.of());
                SecurityContextHolder.getContext()
                .setAuthentication(auth);
            }
        }
        filterChain.doFilter(request, response);
    }
    
}
