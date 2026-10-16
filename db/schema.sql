-- =====================================================================
-- Inventory & Sales Management API: Phase 1 schema (MySQL 8.0+)
-- Multi-tenant (business_id everywhere), locations, periodic stock-takes
-- Revenue / sales / profit are NOT stored: computed in the service layer.
-- =====================================================================

CREATE DATABASE IF NOT EXISTS inventory_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
USE inventory_db;

-- ---------------------------------------------------------------------
-- 1. BUSINESSES (tenants) and their settings
-- ---------------------------------------------------------------------
CREATE TABLE businesses (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name          VARCHAR(150) NOT NULL,
  is_active     TINYINT(1) NOT NULL DEFAULT 1,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB;

CREATE TABLE business_settings (
  business_id        BIGINT UNSIGNED NOT NULL,
  currency_code      CHAR(3) NOT NULL DEFAULT 'UGX',
  period_length      ENUM('weekly','monthly') NOT NULL DEFAULT 'monthly',
  cost_rule          ENUM('weighted_average','latest','per_batch') NOT NULL DEFAULT 'weighted_average',
  -- Reserved for Phase 2 (transfers); harmless until used
  transfers_enabled  TINYINT(1) NOT NULL DEFAULT 0,
  transfer_approval  ENUM('none','receiver_confirms','owner_approves') NOT NULL DEFAULT 'receiver_confirms',
  transfer_initiators ENUM('owner_only','owner_and_managers') NOT NULL DEFAULT 'owner_and_managers',
  PRIMARY KEY (business_id),
  CONSTRAINT fk_settings_business FOREIGN KEY (business_id) REFERENCES businesses (id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2. LOCATIONS (branches)
-- ---------------------------------------------------------------------
CREATE TABLE locations (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id  BIGINT UNSIGNED NOT NULL,
  name         VARCHAR(150) NOT NULL,
  address      VARCHAR(255) NULL,
  is_active    TINYINT(1) NOT NULL DEFAULT 1,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_location_tenant (id, business_id),          -- target for composite FKs
  UNIQUE KEY uq_location_name (business_id, name),
  CONSTRAINT fk_location_business FOREIGN KEY (business_id) REFERENCES businesses (id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. USERS, MEMBERSHIPS (role per business), and location access
-- ---------------------------------------------------------------------
CREATE TABLE users (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  email          VARCHAR(190) NOT NULL,
  password_hash  VARCHAR(255) NOT NULL,
  full_name      VARCHAR(150) NOT NULL,
  is_active      TINYINT(1) NOT NULL DEFAULT 1,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_user_email (email)
) ENGINE=InnoDB;

CREATE TABLE memberships (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id  BIGINT UNSIGNED NOT NULL,
  user_id      BIGINT UNSIGNED NOT NULL,
  role         ENUM('owner','manager','salesperson') NOT NULL,
  is_active    TINYINT(1) NOT NULL DEFAULT 1,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_membership_tenant (id, business_id),
  UNIQUE KEY uq_membership_user (business_id, user_id),
  CONSTRAINT fk_membership_business FOREIGN KEY (business_id) REFERENCES businesses (id),
  CONSTRAINT fk_membership_user     FOREIGN KEY (user_id)     REFERENCES users (id)
) ENGINE=InnoDB;

-- Which locations a manager/salesperson may work in (owners see all)
CREATE TABLE membership_locations (
  membership_id BIGINT UNSIGNED NOT NULL,
  location_id   BIGINT UNSIGNED NOT NULL,
  business_id   BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (membership_id, location_id),
  CONSTRAINT fk_ml_membership FOREIGN KEY (membership_id, business_id)
    REFERENCES memberships (id, business_id),
  CONSTRAINT fk_ml_location FOREIGN KEY (location_id, business_id)
    REFERENCES locations (id, business_id)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. PRODUCTS (catalog is business-level; stock is location-level)
-- ---------------------------------------------------------------------
CREATE TABLE products (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id    BIGINT UNSIGNED NOT NULL,
  name           VARCHAR(150) NOT NULL,
  sku            VARCHAR(60) NULL,
  unit           VARCHAR(20) NOT NULL DEFAULT 'pcs',          -- pcs, kg, litre...
  selling_price  DECIMAL(12,2) NOT NULL DEFAULT 0.00,         -- current/default price
  is_active      TINYINT(1) NOT NULL DEFAULT 1,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_product_tenant (id, business_id),
  UNIQUE KEY uq_product_name (business_id, name),
  UNIQUE KEY uq_product_sku (business_id, sku),
  CONSTRAINT fk_product_business FOREIGN KEY (business_id) REFERENCES businesses (id),
  CONSTRAINT chk_product_price CHECK (selling_price >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5. PERIODS (one stock-take cycle per location)
-- ---------------------------------------------------------------------
CREATE TABLE periods (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id  BIGINT UNSIGNED NOT NULL,
  location_id  BIGINT UNSIGNED NOT NULL,
  start_date   DATE NOT NULL,
  end_date     DATE NOT NULL,
  status       ENUM('open','closed') NOT NULL DEFAULT 'open',
  closed_at    TIMESTAMP NULL,
  closed_by    BIGINT UNSIGNED NULL,
  created_at   TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_period_scope (id, business_id, location_id), -- target for composite FKs
  UNIQUE KEY uq_period_start (location_id, start_date),
  KEY idx_period_lookup (business_id, location_id, status),
  CONSTRAINT fk_period_location FOREIGN KEY (location_id, business_id)
    REFERENCES locations (id, business_id),
  CONSTRAINT fk_period_closed_by FOREIGN KEY (closed_by) REFERENCES users (id),
  CONSTRAINT chk_period_dates CHECK (end_date >= start_date)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 6. STOCK ENTRIES (goods received during a period)
-- ---------------------------------------------------------------------
CREATE TABLE stock_entries (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id   BIGINT UNSIGNED NOT NULL,
  location_id   BIGINT UNSIGNED NOT NULL,
  period_id     BIGINT UNSIGNED NOT NULL,
  product_id    BIGINT UNSIGNED NOT NULL,
  quantity      DECIMAL(12,3) NOT NULL,
  buying_price  DECIMAL(12,2) NOT NULL,                       -- per unit
  entry_date    DATE NOT NULL,
  recorded_by   BIGINT UNSIGNED NOT NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_entry_period_product (period_id, product_id),
  KEY idx_entry_tenant (business_id, location_id),
  CONSTRAINT fk_entry_period FOREIGN KEY (period_id, business_id, location_id)
    REFERENCES periods (id, business_id, location_id),
  CONSTRAINT fk_entry_product FOREIGN KEY (product_id, business_id)
    REFERENCES products (id, business_id),
  CONSTRAINT fk_entry_user FOREIGN KEY (recorded_by) REFERENCES users (id),
  CONSTRAINT chk_entry_qty CHECK (quantity > 0),
  CONSTRAINT chk_entry_price CHECK (buying_price >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 7. PERIOD COUNTS (the stock-take)
-- ---------------------------------------------------------------------
CREATE TABLE period_counts (
  id                 BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id        BIGINT UNSIGNED NOT NULL,
  location_id        BIGINT UNSIGNED NOT NULL,
  period_id          BIGINT UNSIGNED NOT NULL,
  product_id         BIGINT UNSIGNED NOT NULL,
  opening_qty        DECIMAL(12,3) NOT NULL DEFAULT 0,
  opening_unit_cost  DECIMAL(12,2) NOT NULL DEFAULT 0.00,
  entries_qty        DECIMAL(12,3) NOT NULL DEFAULT 0,
  entries_cost       DECIMAL(12,2) NOT NULL DEFAULT 0.00,
  sold_qty           DECIMAL(12,3) NOT NULL DEFAULT 0,
  unsold_qty         DECIMAL(12,3) NULL,
  lost_damaged_qty   DECIMAL(12,3) NOT NULL DEFAULT 0,
  selling_price      DECIMAL(12,2) NOT NULL DEFAULT 0.00,
  unit_cost_used     DECIMAL(12,2) NULL,
  recorded_by        BIGINT UNSIGNED NULL,
  created_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at         TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uq_count_period_product (period_id, product_id),
  KEY idx_count_tenant (business_id, location_id),
  CONSTRAINT fk_count_period FOREIGN KEY (period_id, business_id, location_id)
    REFERENCES periods (id, business_id, location_id),
  CONSTRAINT fk_count_product FOREIGN KEY (product_id, business_id)
    REFERENCES products (id, business_id),
  CONSTRAINT fk_count_recorder FOREIGN KEY (recorded_by) REFERENCES users (id),
  CONSTRAINT chk_count_non_negative CHECK (opening_qty >= 0 AND entries_qty >= 0 AND sold_qty >= 0 AND lost_damaged_qty >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 8. SALES (transactions during a period)
-- ---------------------------------------------------------------------
CREATE TABLE sales (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id    BIGINT UNSIGNED NOT NULL,
  location_id    BIGINT UNSIGNED NOT NULL,
  period_id      BIGINT UNSIGNED NOT NULL,
  product_id     BIGINT UNSIGNED NOT NULL,
  quantity       DECIMAL(12,3) NOT NULL,
  unit_price     DECIMAL(12,2) NOT NULL,
  sold_at        TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  recorded_by    BIGINT UNSIGNED NOT NULL,
  PRIMARY KEY (id),
  KEY idx_sales_period_product (period_id, product_id),
  CONSTRAINT fk_sale_period FOREIGN KEY (period_id, business_id, location_id)
    REFERENCES periods (id, business_id, location_id),
  CONSTRAINT fk_sale_product FOREIGN KEY (product_id, business_id)
    REFERENCES products (id, business_id),
  CONSTRAINT fk_sale_user FOREIGN KEY (recorded_by) REFERENCES users (id),
  CONSTRAINT chk_sale_qty CHECK (quantity > 0),
  CONSTRAINT chk_sale_price CHECK (unit_price >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 9. DIRECT LOSSES / DAMAGED GOODS
-- ---------------------------------------------------------------------
CREATE TABLE stock_losses (
  id              BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id     BIGINT UNSIGNED NOT NULL,
  location_id     BIGINT UNSIGNED NOT NULL,
  period_id       BIGINT UNSIGNED NOT NULL,
  product_id      BIGINT UNSIGNED NOT NULL,
  quantity        DECIMAL(12,3) NOT NULL,
  reason          VARCHAR(150) NOT NULL,
  loss_date       DATE NOT NULL,
  recorded_by     BIGINT UNSIGNED NOT NULL,
  created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_loss_period_product (period_id, product_id),
  CONSTRAINT fk_loss_period FOREIGN KEY (period_id, business_id, location_id)
    REFERENCES periods (id, business_id, location_id),
  CONSTRAINT fk_loss_product FOREIGN KEY (product_id, business_id)
    REFERENCES products (id, business_id),
  CONSTRAINT fk_loss_user FOREIGN KEY (recorded_by) REFERENCES users (id),
  CONSTRAINT chk_loss_qty CHECK (quantity > 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 10. OPTIONAL: audit trail placeholder
-- ---------------------------------------------------------------------
CREATE TABLE audit_log (
  id            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  business_id   BIGINT UNSIGNED NOT NULL,
  entity_type   VARCHAR(50) NOT NULL,
  entity_id     BIGINT UNSIGNED NOT NULL,
  action        VARCHAR(50) NOT NULL,
  details       JSON NULL,
  created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_audit_business (business_id)
) ENGINE=InnoDB;
