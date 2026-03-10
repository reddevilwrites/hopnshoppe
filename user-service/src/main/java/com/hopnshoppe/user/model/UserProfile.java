package com.hopnshoppe.user.model;

import jakarta.persistence.*;
import jakarta.validation.constraints.Email;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.AllArgsConstructor;
import lombok.Data;
import lombok.NoArgsConstructor;

/**
 * Owns all non-sensitive user data for the user-service database (hopnshoppe_user_db).
 *
 * <p>Migrated from the monolith's {@code User} entity with the {@code password} field
 * deliberately removed — credentials live exclusively in auth-service/auth_db.
 *
 * <p>{@code email} is the canonical cross-service identifier; it is duplicated here
 * (also stored in auth-service's {@code credentials} table) because database-per-service
 * forbids cross-DB foreign keys. Consistency is maintained at the application layer:
 * auth-service creates a credential record, then calls this service's internal API to
 * create the matching profile in the same signup transaction.
 */
@Entity
@Table(name = "user_profiles",
       uniqueConstraints = @UniqueConstraint(columnNames = "email"))
@Data
@NoArgsConstructor
@AllArgsConstructor
public class UserProfile {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Email
    @NotNull
    @Column(nullable = false, unique = true)
    private String email;

    @NotNull
    @Size(min = 2, max = 50)
    @Column(name = "first_name", nullable = false)
    private String firstName;

    @NotNull
    @Size(min = 2, max = 50)
    @Column(name = "last_name", nullable = false)
    private String lastName;

    @Pattern(regexp = "^\\+?[0-9]*$", message = "Invalid phone number")
    private String phone;
}
