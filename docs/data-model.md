# Data model

```
User 1───* Vehicle 1───* ServiceRecord 0───* Attachment
                   1───* ServiceInterval
                   1───* FuelLog
                   1───* Attachment
                   1───* TireSet
                   1───* Expense
User 0───* AuditLog          (user_id set NULL when the user is deleted)
```

## User
Account with login credentials. `is_admin` users can manage other users.

| Field            | Type     | Notes                                   |
|------------------|----------|-----------------------------------------|
| `id`             | int PK   |                                         |
| `email`          | str      | unique                                  |
| `username`       | str      | unique                                  |
| `hashed_password`| str      | bcrypt                                  |
| `is_admin`       | bool     | first registered user becomes admin     |
| `is_active`      | bool     | inactive users cannot log in            |
| `locale`         | str      | `de` / `en`                             |
| `totp_secret`    | str/null | base32 TOTP secret, encrypted at rest (set when 2FA on) |
| `totp_enabled`   | bool     | whether 2FA is required at login        |
| `totp_last_used` | int/null | last accepted TOTP time-step — replay protection |
| `totp_recovery_codes` | text/null | JSON list of SHA-256 hashes of one-time 2FA recovery codes |
| `notify_email`   | bool     | receive email reminders (default on)    |
| `session_generation` | int  | bumped on password change / "sign out everywhere" to invalidate other sessions |
| `created_at`     | datetime | account creation time                   |

## Vehicle
A vehicle owned by exactly one user.

| Field           | Type      | Notes                          |
|-----------------|-----------|--------------------------------|
| `name`          | str       | display name (required)        |
| `make` / `model`| str       | optional                       |
| `year`          | int       | optional                       |
| `vin`           | str       | chassis number, optional       |
| `license_plate` | str       | optional                       |
| `fuel_type`     | enum      | petrol/diesel/electric/…       |
| `usage_unit`    | enum      | `km` (distance) or `h` (operating hours) |
| `mileage`       | float     | current odometer / hour-meter reading, in `usage_unit` (up to 2 decimals) |
| `inspection_due`| date      | next roadworthiness inspection (§57a "Pickerl" / TÜV/HU), optional |
| `notes`         | text      | optional                       |

All reading fields below (`ServiceRecord.mileage`, `FuelLog.mileage`,
`ServiceInterval.interval_km` / `last_service_mileage`) are expressed in the
vehicle's `usage_unit` and stored as floats, allowing up to 2 decimal places
(e.g. fractional operating hours or kilometres).

## ServiceRecord
A completed maintenance event (oil change, brake replacement, inspection, …).

| Field          | Type   | Notes                                       |
|----------------|--------|---------------------------------------------|
| `service_type` | enum   | `ServiceType`                               |
| `title`        | str    | short description                           |
| `performed_on` | date   |                                             |
| `mileage`      | float  | optional; bumps the vehicle odometer        |
| `cost`         | float  | optional                                    |
| `workshop`     | str    | optional                                    |

## ServiceInterval
A recurring maintenance rule. Due status is computed from the last service plus
the interval, by **usage** (`interval_km`, in the vehicle's `usage_unit`) and/or
**time** (`interval_months`). Status is `ok` / `due_soon` (within ≤1000 km /
≤50 h, or ≤30 days) / `overdue` / `unknown`.

| Field                  | Type | Notes                       |
|------------------------|------|-----------------------------|
| `name`                 | str  | e.g. "Oil change"           |
| `service_type`         | enum |                             |
| `interval_km`          | float | optional                   |
| `interval_months`      | int  | optional                    |
| `last_service_date`    | date | optional                    |
| `last_service_mileage` | float | optional                   |

## FuelLog
A refueling / charging event.

| Field            | Type  | Notes                                  |
|------------------|-------|----------------------------------------|
| `filled_on`      | date  |                                        |
| `mileage`        | float | optional; bumps the vehicle odometer   |
| `quantity`       | float | liters or kWh                          |
| `price_per_unit` | float | optional                               |
| `total_cost`     | float | derived from price × quantity if blank |
| `full_tank`      | bool  | for consumption calculations           |

## Attachment
An uploaded document or photo (invoice, receipt, vehicle picture). Files are
stored on disk under `FLEETBOX_UPLOAD_DIR` with an opaque random name; only the
metadata below is kept in the database. Allowed types: JPEG, PNG, GIF, WebP and
PDF, capped at `FLEETBOX_MAX_UPLOAD_BYTES` (10 MiB by default).

| Field               | Type     | Notes                                            |
|---------------------|----------|--------------------------------------------------|
| `vehicle_id`        | int FK   | owning vehicle (cascade delete)                  |
| `service_record_id` | int/null | optional link to a record (`SET NULL` on delete) |
| `title`             | str/null | optional label                                   |
| `filename`          | str      | original upload name                             |
| `stored_name`       | str      | opaque name on disk                              |
| `content_type`      | str      | validated MIME type                              |
| `size`              | int      | bytes                                            |
| `is_primary`        | bool     | this image is the vehicle's photo / title image (≤1 per vehicle, managed on the vehicle form) |
| `uploaded_at`       | datetime |                                                  |

## TireSet
A set of tyres for a vehicle. The seasonal reminder (dashboard + email) fires
in the configured month when the vehicle owns a set for the upcoming season that
is not the one currently mounted.

| Field              | Type     | Notes                                          |
|--------------------|----------|------------------------------------------------|
| `vehicle_id`       | int FK   | owning vehicle (cascade delete)                |
| `season`           | enum     | `summer` / `winter` / `all_season`             |
| `label`            | str/null | e.g. brand / model                             |
| `dimension`        | str/null | e.g. `205/55 R16`                              |
| `storage_location` | str/null | where the set is stored when off the vehicle   |
| `tread_depth_mm`   | float    | optional                                       |
| `is_mounted`       | bool     | currently on the vehicle (≤1 mounted per vehicle) |
| `mounted_on`       | date     | recorded when mounted                          |
| `mounted_mileage`  | float    | vehicle reading when mounted                   |

Mounting a set automatically unmounts any other set on the vehicle.

## Expense
A miscellaneous vehicle expense that is neither fuel nor a service record
(insurance, road tax, parking, tolls, the Austrian motorway vignette, fines,
accessories, …). Expenses count towards the vehicle's total cost and the monthly
cost chart on the statistics page.

| Field        | Type   | Notes                                  |
|--------------|--------|----------------------------------------|
| `vehicle_id` | int FK | owning vehicle (cascade delete)        |
| `category`   | enum   | `ExpenseCategory`                      |
| `title`      | str    | short description                      |
| `amount`     | float  | cost in the instance's currency        |
| `spent_on`   | date   |                                        |
| `notes`      | text   | optional                               |

## AuditLog
Security-relevant events: logins and failed attempts, logouts, registrations,
password and 2FA changes, admin user management, and "sign out everywhere".
Visible to administrators under **Users → Audit log**. `username` is a snapshot
so entries stay meaningful after a user is renamed or deleted; entries are not
tied to any single vehicle.

| Field        | Type     | Notes                                              |
|--------------|----------|----------------------------------------------------|
| `user_id`    | int/null | acting user; `SET NULL` if that user is deleted    |
| `username`   | str/null | snapshot of the acting / attempted identity        |
| `event`      | str      | event key, e.g. `login.success`, `password.changed`, `sessions.revoked_others` |
| `detail`     | str/null | extra context (e.g. the affected username)         |
| `ip`         | str/null | client IP address                                  |
| `created_at` | datetime | event time (UTC)                                   |

## ServiceType values
`oil_change`, `brake_replacement`, `wear_part`, `inspection`, `tyre_change`,
`chain`, `repair`, `other`

## TireSeason values
`summer`, `winter`, `all_season`

## ExpenseCategory values
`insurance`, `tax`, `registration`, `parking`, `toll`, `vignette`, `fine`,
`accessory`, `cleaning`, `other`

## FuelType values
`petrol`, `diesel`, `electric`, `hybrid`, `other` — plus the retired values
`lpg` and `cng`, which are no longer offered in the vehicle form but remain
valid so existing vehicles and old backups keep loading.

## UsageUnit values
`km` (distance), `h` (operating hours). Drives every reading's label and the
statistics: distance vehicles report consumption per 100 km and cost per km,
hour-based vehicles report consumption per hour and cost per hour.
