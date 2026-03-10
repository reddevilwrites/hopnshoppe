package com.hopnshoppe.auth.repository;

import com.hopnshoppe.auth.model.Credential;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface CredentialRepository extends JpaRepository<Credential, Long> {

    Optional<Credential> findByEmail(String email);

    boolean existsByEmail(String email);

    void deleteByEmail(String email);
}
