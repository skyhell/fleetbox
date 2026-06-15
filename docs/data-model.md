# Data model

```
User 1───* Vehicle 1───* ServiceRecord
                   1───* ServiceInterval
                   1───* FuelLog
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
| `mileage`       | int       | current odometer (km)          |
| `notes`         | text      | optional                       |

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
the interval, by **distance** (`interval_km`) and/or **time**
(`interval_months`). Status is `ok` / `due_soon` (≤1000 km or ≤30 days) /
`overdue` / `unknown`.

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

## ServiceType values
`oil_change`, `brake_replacement`, `wear_part`, `inspection`, `tyre_change`,
`repair`, `other`

## FuelType values
`petrol`, `diesel`, `electric`, `lpg`, `cng`, `hybrid`, `other`
