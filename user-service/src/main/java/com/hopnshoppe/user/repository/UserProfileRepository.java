package com.hopnshoppe.user.repository;

import com.hopnshoppe.user.model.UserProfile;
import org.springframework.data.jpa.repository.JpaRepository;

import java.util.Optional;

public interface UserProfileRepository extends JpaRepository<UserProfile, Long> {

    /** Used by InternalUserController when auth-service looks up a profile by email. */
    Optional<UserProfile> findByEmail(String email);

    boolean existsByEmail(String email);

    void deleteByEmail(String email);
}
