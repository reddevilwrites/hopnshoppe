package com.wknd.spring.client.config_client.repository;

import org.springframework.data.jpa.repository.JpaRepository;

import com.wknd.spring.client.config_client.model.User;

public interface UserRepository extends JpaRepository<User, Long>{
    boolean existsByEmail(String email);
    User findByEmail(String email);
    
}
