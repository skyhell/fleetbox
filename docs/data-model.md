# Data model

```
User 1───* Vehicle 1───* ServiceRecord 0───* Attachment
                   1───* ServiceInterval
                   1───* FuelLog
                   1───* Attachment
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
| `totp_secret`    | str/null | base32 TOTP secret (set when 2FA on)    |
| `totp_enabled`   | bool     | whether 2FA is required at login        |

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
| `mileage`       | int       | current odometer / hour-meter reading, in `usage_unit` |
| `notes`         | text      | optional                       |

All reading fields below (`ServiceRecord.mileage`, `FuelLog.mileage`,
`ServiceInterval.interval_km` / `last_service_mileage`) are expressed in the
vehicle's `usage_unit`.

## ServiceRecord
A completed maintenance event (oil change, brake replacement, inspection, …).

| Field          | Type   | Notes                                       |
|----------------|--------|---------------------------------------------|
| `service_type` | enum   | `ServiceType`                               |
| `title`        | str    | short description                           |
| `performed_on` | date   |                                             |
| `mileage`      | int    | optional; bumps the vehicle odometer        |
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
| `interval_km`          | int  | optional                    |
| `interval_months`      | int  | optional                    |
| `last_service_date`    | date | optional                    |
| `last_service_mileage` | int  | optional                    |

## FuelLog
A refueling / charging event.

| Field            | Type  | Notes                                  |
|------------------|-------|----------------------------------------|
| `filled_on`      | date  |                                        |
| `mileage`        | int   | optional; bumps the vehicle odometer   |
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
| `uploaded_at`       | datetime |                                                  |

## ServiceType values
`oil_change`, `brake_replacement`, `wear_part`, `inspection`, `tyre_change`,
`repair`, `other`

## FuelType values
`petrol`, `diesel`, `electric`, `lpg`, `cng`, `hybrid`, `other`

## UsageUnit values
`km` (distance), `h` (operating hours). Drives every reading's label and the
statistics: distance vehicles report consumption per 100 km and cost per km,
hour-based vehicles report consumption per hour and cost per hour.
