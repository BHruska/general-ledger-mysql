-- General Ledger v0.6.1
-- File: docker/dev-initdb/02-demo.sql
-- Description: Demo data: "Bluebird Design Studio LLC", three months to 2026-10-01,
--              made by `python manage.py make-demo` and dumped with mysqldump.
--              Loaded into `gl` on the dev database's FIRST start (empty volume) only.
--              Sign in with the password  bluebird-demo  (dev/demo only).
--              To start empty instead, delete this file before the first `up`;
--              to reload it: docker compose -f compose.dev.yml down -v
-- MySQL dump 10.13  Distrib 8.0.46, for Linux (x86_64)
--
-- Host: localhost    Database: gl
-- ------------------------------------------------------
-- Server version	8.0.46

/*!40101 SET @OLD_CHARACTER_SET_CLIENT=@@CHARACTER_SET_CLIENT */;
/*!40101 SET @OLD_CHARACTER_SET_RESULTS=@@CHARACTER_SET_RESULTS */;
/*!40101 SET @OLD_COLLATION_CONNECTION=@@COLLATION_CONNECTION */;
/*!50503 SET NAMES utf8mb4 */;
/*!40103 SET @OLD_TIME_ZONE=@@TIME_ZONE */;
/*!40103 SET TIME_ZONE='+00:00' */;
/*!40014 SET @OLD_UNIQUE_CHECKS=@@UNIQUE_CHECKS, UNIQUE_CHECKS=0 */;
/*!40014 SET @OLD_FOREIGN_KEY_CHECKS=@@FOREIGN_KEY_CHECKS, FOREIGN_KEY_CHECKS=0 */;
/*!40101 SET @OLD_SQL_MODE=@@SQL_MODE, SQL_MODE='NO_AUTO_VALUE_ON_ZERO' */;
/*!40111 SET @OLD_SQL_NOTES=@@SQL_NOTES, SQL_NOTES=0 */;

--
-- Table structure for table `account`
--

DROP TABLE IF EXISTS `account`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `account` (
  `id` int NOT NULL AUTO_INCREMENT,
  `number` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `type` enum('ASSET','LIABILITY','EQUITY','INCOME','EXPENSE') COLLATE utf8mb4_unicode_ci NOT NULL,
  `parent_id` int DEFAULT NULL,
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `is_bank_account` tinyint(1) NOT NULL DEFAULT '0',
  `tax_line` varchar(60) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `is_1099_expense` tinyint(1) NOT NULL DEFAULT '0',
  `description` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_account_number` (`number`),
  KEY `parent_id` (`parent_id`),
  CONSTRAINT `account_ibfk_1` FOREIGN KEY (`parent_id`) REFERENCES `account` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=25 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `account`
--

LOCK TABLES `account` WRITE;
/*!40000 ALTER TABLE `account` DISABLE KEYS */;
INSERT INTO `account` VALUES (1,'1010','Business Checking','ASSET',NULL,1,1,NULL,0,NULL),(2,'1200','Accounts Receivable','ASSET',NULL,1,0,NULL,0,NULL),(3,'2010','Business Card','LIABILITY',NULL,1,1,NULL,0,NULL),(4,'2200','Owner Loan','LIABILITY',NULL,1,0,NULL,0,NULL),(5,'3000','Owner\'s Equity','EQUITY',NULL,1,0,NULL,0,NULL),(6,'3100','Owner Draws','EQUITY',NULL,1,0,NULL,0,NULL),(7,'3900','Retained Earnings','EQUITY',NULL,1,0,NULL,0,NULL),(8,'4000','Design Services','INCOME',NULL,1,0,NULL,0,NULL),(9,'4900','Other Income','INCOME',NULL,1,0,NULL,0,NULL),(10,'6000','Advertising','EXPENSE',NULL,1,0,NULL,0,NULL),(11,'6050','Bank and Card Fees','EXPENSE',NULL,1,0,NULL,0,NULL),(12,'6100','Software','EXPENSE',NULL,1,0,NULL,0,NULL),(13,'6110','Hosting','EXPENSE',12,1,0,NULL,0,NULL),(14,'6120','SaaS Subscriptions','EXPENSE',12,1,0,NULL,0,NULL),(15,'6200','Telephone and Internet','EXPENSE',NULL,1,0,NULL,0,NULL),(16,'6300','Travel','EXPENSE',NULL,1,0,NULL,0,NULL),(17,'6350','Meals','EXPENSE',NULL,1,0,NULL,0,NULL),(18,'6400','Office Supplies','EXPENSE',NULL,1,0,NULL,0,NULL),(19,'6500','Professional Fees','EXPENSE',NULL,1,0,NULL,1,NULL),(20,'6600','Insurance','EXPENSE',NULL,1,0,NULL,0,NULL),(21,'6700','Contract Labor','EXPENSE',NULL,1,0,NULL,1,NULL),(22,'6800','Taxes and Licenses','EXPENSE',NULL,1,0,NULL,0,NULL),(23,'6900','Miscellaneous','EXPENSE',NULL,1,0,NULL,0,NULL),(24,'6250','Rent','EXPENSE',NULL,1,0,NULL,0,NULL);
/*!40000 ALTER TABLE `account` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `alembic_version`
--

DROP TABLE IF EXISTS `alembic_version`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `alembic_version` (
  `version_num` varchar(32) COLLATE utf8mb4_unicode_ci NOT NULL,
  PRIMARY KEY (`version_num`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `alembic_version`
--

LOCK TABLES `alembic_version` WRITE;
/*!40000 ALTER TABLE `alembic_version` DISABLE KEYS */;
INSERT INTO `alembic_version` VALUES ('0008');
/*!40000 ALTER TABLE `alembic_version` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `attachment`
--

DROP TABLE IF EXISTS `attachment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `attachment` (
  `id` int NOT NULL AUTO_INCREMENT,
  `entry_id` bigint DEFAULT NULL,
  `bank_txn_id` bigint DEFAULT NULL,
  `filename` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `stored_path` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `sha256` char(64) COLLATE utf8mb4_unicode_ci NOT NULL,
  `content_type` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `size_bytes` int NOT NULL,
  `uploaded_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `ix_attachment_bank_txn` (`bank_txn_id`),
  KEY `ix_attachment_entry` (`entry_id`),
  CONSTRAINT `attachment_ibfk_1` FOREIGN KEY (`entry_id`) REFERENCES `journal_entry` (`id`),
  CONSTRAINT `attachment_ibfk_2` FOREIGN KEY (`bank_txn_id`) REFERENCES `bank_txn` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `attachment`
--

LOCK TABLES `attachment` WRITE;
/*!40000 ALTER TABLE `attachment` DISABLE KEYS */;
/*!40000 ALTER TABLE `attachment` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `audit_log`
--

DROP TABLE IF EXISTS `audit_log`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `audit_log` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `at` datetime(6) NOT NULL,
  `action` varchar(60) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_type` varchar(40) COLLATE utf8mb4_unicode_ci NOT NULL,
  `object_id` bigint DEFAULT NULL,
  `detail` json DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=32 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `audit_log`
--

LOCK TABLES `audit_log` WRITE;
/*!40000 ALTER TABLE `audit_log` DISABLE KEYS */;
INSERT INTO `audit_log` VALUES (1,'2026-10-01 19:34:44.728201','settings.update','settings',1,'{\"default_income_account_id\": {\"new\": 8, \"old\": null}}'),(2,'2026-10-01 19:34:44.807887','bank_account.create','bank_account',1,'{\"gl_account_id\": 1, \"feed_start_date\": \"2026-07-01\"}'),(3,'2026-10-01 19:34:44.833082','bank_account.create','bank_account',2,'{\"gl_account_id\": 3, \"feed_start_date\": \"2026-07-01\"}'),(4,'2026-10-01 19:34:44.860373','customer.create','payee',1,'{\"name\": \"Acme Dental Group\"}'),(5,'2026-10-01 19:34:44.876366','customer.create','payee',2,'{\"name\": \"Riverside Bakery\"}'),(6,'2026-10-01 19:34:44.893611','customer.create','payee',3,'{\"name\": \"Harbor Law Partners\"}'),(7,'2026-10-01 19:34:44.916739','customer.create','payee',4,'{\"name\": \"Summit Fitness\"}'),(8,'2026-10-01 19:34:45.770879','invoice.issue','invoice',1,'{\"total\": \"1500.00\", \"number\": \"INV-1001\", \"entry_id\": 2}'),(9,'2026-10-01 19:34:45.882189','invoice.issue','invoice',2,'{\"total\": \"1020.00\", \"number\": \"INV-1002\", \"entry_id\": 3}'),(10,'2026-10-01 19:34:45.989381','invoice.issue','invoice',3,'{\"total\": \"1500.00\", \"number\": \"INV-1003\", \"entry_id\": 4}'),(11,'2026-10-01 19:34:46.087407','invoice.issue','invoice',4,'{\"total\": \"2400.00\", \"number\": \"INV-1004\", \"entry_id\": 5}'),(12,'2026-10-01 19:34:46.189175','invoice.issue','invoice',5,'{\"total\": \"500.00\", \"number\": \"INV-1005\", \"entry_id\": 6}'),(13,'2026-10-01 19:34:46.294198','invoice.issue','invoice',6,'{\"total\": \"1500.00\", \"number\": \"INV-1006\", \"entry_id\": 7}'),(14,'2026-10-01 19:34:46.394348','invoice.issue','invoice',7,'{\"total\": \"382.50\", \"number\": \"INV-1007\", \"entry_id\": 8}'),(15,'2026-10-01 19:34:46.593150','bank.import','bank_account',2,'{\"file\": \"demo-card.csv\", \"rows\": 30, \"added\": 30, \"layout\": \"CHASE_CARD\", \"before_start\": 0, \"overlaps_feed\": 0, \"already_present\": 0}'),(16,'2026-10-01 19:34:46.723584','bank.import','bank_account',1,'{\"file\": \"demo-checking.csv\", \"rows\": 18, \"added\": 18, \"layout\": \"CHASE_CHECKING\", \"before_start\": 0, \"overlaps_feed\": 0, \"already_present\": 0}'),(17,'2026-10-01 19:34:46.822290','rule.remember','payee_rule',1,'{\"pattern\": \"SUNRISE PROPERTIES\", \"updated\": false, \"account_id\": 24}'),(18,'2026-10-01 19:34:46.956297','rule.remember','payee_rule',2,'{\"pattern\": \"ADOBE *CREATIVE CLD\", \"updated\": false, \"account_id\": 14}'),(19,'2026-10-01 19:34:47.081396','rule.remember','payee_rule',3,'{\"pattern\": \"GOOGLE *WORKSPACE BLUEB\", \"updated\": false, \"account_id\": 14}'),(20,'2026-10-01 19:34:47.208100','rule.remember','payee_rule',4,'{\"pattern\": \"DIGITALOCEAN.COM\", \"updated\": false, \"account_id\": 13}'),(21,'2026-10-01 19:34:47.327177','rule.remember','payee_rule',5,'{\"pattern\": \"VERIZON WIRELESS\", \"updated\": false, \"account_id\": 15}'),(22,'2026-10-01 19:34:47.440611','rule.remember','payee_rule',6,'{\"pattern\": \"ZOOM.US\", \"updated\": false, \"account_id\": 14}'),(23,'2026-10-01 19:34:47.574735','rule.remember','payee_rule',7,'{\"pattern\": \"BLUE BOTTLE COFFEE\", \"updated\": false, \"account_id\": 17}'),(24,'2026-10-01 19:34:47.702522','rule.remember','payee_rule',8,'{\"pattern\": \"STAPLES\", \"updated\": false, \"account_id\": 18}'),(25,'2026-10-01 19:34:47.913086','rule.remember','payee_rule',9,'{\"pattern\": \"PANERA BREAD\", \"updated\": false, \"account_id\": 17}'),(26,'2026-10-01 19:34:48.117968','rule.remember','payee_rule',10,'{\"pattern\": \"Online Transfer to\", \"updated\": false, \"account_id\": 6}'),(27,'2026-10-01 19:34:48.275666','rule.remember','payee_rule',11,'{\"pattern\": \"MONTHLY SERVICE FEE\", \"updated\": false, \"account_id\": 11}'),(28,'2026-10-01 19:34:49.218927','rule.remember','payee_rule',12,'{\"pattern\": \"UNITED\", \"updated\": false, \"account_id\": 16}'),(29,'2026-10-01 19:34:49.790248','rule.remember','payee_rule',13,'{\"pattern\": \"HILTON HOTELS CHICAGO\", \"updated\": false, \"account_id\": 16}'),(30,'2026-10-01 19:34:51.872281','rule.remember','payee_rule',14,'{\"pattern\": \"FACEBOOK *ADS\", \"updated\": false, \"account_id\": 10}'),(31,'2026-10-01 19:34:52.410474','lock_date.move','settings',1,'{\"new\": \"2026-07-31\", \"old\": null, \"reason\": null, \"backwards\": false}');
/*!40000 ALTER TABLE `audit_log` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `bank_account`
--

DROP TABLE IF EXISTS `bank_account`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bank_account` (
  `id` int NOT NULL AUTO_INCREMENT,
  `connection_id` int NOT NULL,
  `gl_account_id` int NOT NULL,
  `provider_account_id` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `kind` enum('DEPOSITORY','CREDIT') COLLATE utf8mb4_unicode_ci NOT NULL,
  `mask` varchar(8) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `name` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `feed_start_date` date NOT NULL,
  `reported_balance` decimal(14,2) DEFAULT NULL,
  `reported_balance_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_gl_account` (`gl_account_id`),
  KEY `connection_id` (`connection_id`),
  CONSTRAINT `bank_account_ibfk_1` FOREIGN KEY (`connection_id`) REFERENCES `bank_connection` (`id`),
  CONSTRAINT `bank_account_ibfk_2` FOREIGN KEY (`gl_account_id`) REFERENCES `account` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=3 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `bank_account`
--

LOCK TABLES `bank_account` WRITE;
/*!40000 ALTER TABLE `bank_account` DISABLE KEYS */;
INSERT INTO `bank_account` VALUES (1,1,1,NULL,'DEPOSITORY','1234','Business Checking','2026-07-01',11830.65,'2026-09-27 00:00:00.000000'),(2,1,3,NULL,'CREDIT','5678','Business Card','2026-07-01',NULL,NULL);
/*!40000 ALTER TABLE `bank_account` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `bank_connection`
--

DROP TABLE IF EXISTS `bank_connection`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bank_connection` (
  `id` int NOT NULL AUTO_INCREMENT,
  `provider` enum('PLAID','SIMPLEFIN','FILE') COLLATE utf8mb4_unicode_ci NOT NULL,
  `institution` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `credential_ref` varchar(60) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `provider_item_id` varchar(100) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `sync_cursor` text COLLATE utf8mb4_unicode_ci,
  `status` enum('OK','LOGIN_REQUIRED','ERROR','DISCONNECTED') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'OK',
  `status_detail` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `consent_expires_at` datetime(6) DEFAULT NULL,
  `last_synced_at` datetime(6) DEFAULT NULL,
  `sync_requested_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=2 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `bank_connection`
--

LOCK TABLES `bank_connection` WRITE;
/*!40000 ALTER TABLE `bank_connection` DISABLE KEYS */;
INSERT INTO `bank_connection` VALUES (1,'FILE','Demo Bank',NULL,NULL,NULL,'OK',NULL,NULL,NULL,NULL);
/*!40000 ALTER TABLE `bank_connection` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `bank_txn`
--

DROP TABLE IF EXISTS `bank_txn`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `bank_txn` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `bank_account_id` int NOT NULL,
  `source` enum('PLAID','SIMPLEFIN','FILE') COLLATE utf8mb4_unicode_ci NOT NULL,
  `external_id` varchar(100) COLLATE utf8mb4_unicode_ci NOT NULL,
  `posted_date` date NOT NULL,
  `amount` decimal(14,2) NOT NULL,
  `description` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `merchant_name` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `provider_category` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` enum('NEW','SUGGESTED','POSTED','EXCLUDED','REMOVED') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'NEW',
  `suggested_account_id` int DEFAULT NULL,
  `suggested_payee_id` int DEFAULT NULL,
  `suggested_rule_id` int DEFAULT NULL,
  `suggested_invoice_id` int DEFAULT NULL,
  `suggested_transfer_txn_id` bigint DEFAULT NULL,
  `entry_id` bigint DEFAULT NULL,
  `excluded_reason` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `raw_json` json NOT NULL,
  `first_seen_at` datetime(6) NOT NULL,
  `suggestion_reason` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_bank_txn` (`bank_account_id`,`source`,`external_id`),
  KEY `suggested_account_id` (`suggested_account_id`),
  KEY `suggested_payee_id` (`suggested_payee_id`),
  KEY `suggested_transfer_txn_id` (`suggested_transfer_txn_id`),
  KEY `entry_id` (`entry_id`),
  KEY `ix_bank_txn_status` (`status`,`posted_date`),
  KEY `fk_bank_txn_rule` (`suggested_rule_id`),
  KEY `fk_bank_txn_invoice` (`suggested_invoice_id`),
  CONSTRAINT `bank_txn_ibfk_1` FOREIGN KEY (`bank_account_id`) REFERENCES `bank_account` (`id`),
  CONSTRAINT `bank_txn_ibfk_2` FOREIGN KEY (`suggested_account_id`) REFERENCES `account` (`id`),
  CONSTRAINT `bank_txn_ibfk_3` FOREIGN KEY (`suggested_payee_id`) REFERENCES `payee` (`id`),
  CONSTRAINT `bank_txn_ibfk_4` FOREIGN KEY (`suggested_transfer_txn_id`) REFERENCES `bank_txn` (`id`),
  CONSTRAINT `bank_txn_ibfk_5` FOREIGN KEY (`entry_id`) REFERENCES `journal_entry` (`id`),
  CONSTRAINT `fk_bank_txn_invoice` FOREIGN KEY (`suggested_invoice_id`) REFERENCES `invoice` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_bank_txn_rule` FOREIGN KEY (`suggested_rule_id`) REFERENCES `payee_rule` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB AUTO_INCREMENT=49 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `bank_txn`
--

LOCK TABLES `bank_txn` WRITE;
/*!40000 ALTER TABLE `bank_txn` DISABLE KEYS */;
INSERT INTO `bank_txn` VALUES (1,2,'FILE','f0b7b358c79e47033594422a6e5019e290c985f667d9c9082c94d0dc94e620b3','2026-09-26',-12.99,'CANVA* I0451234567',NULL,'Professional Services','NEW',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{\"row\": 2, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-12.99\", \"Category\": \"Professional Services\", \"Post Date\": \"09/26/2026\", \"Description\": \"CANVA* I0451234567\", \"Transaction Date\": \"09/25/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(2,2,'FILE','f16cf22b40e138b8389b17aedc8858391d57360b9d8c59c467d89f2d70844953','2026-09-21',441.71,'AUTOMATIC PAYMENT - THANK',NULL,'Payment','SUGGESTED',NULL,NULL,NULL,NULL,34,NULL,NULL,'{\"row\": 3, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Payment\", \"Amount\": \"441.71\", \"Category\": \"\", \"Post Date\": \"09/21/2026\", \"Description\": \"AUTOMATIC PAYMENT - THANK\", \"Transaction Date\": \"09/20/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','TRANSFER'),(3,2,'FILE','52c3842a266035eecee106be67550e7ce508cce710a8213d56ec7532b287cb17','2026-09-19',-27.40,'PANERA BREAD #4521',NULL,'Food & Drink','SUGGESTED',17,NULL,9,NULL,NULL,NULL,NULL,'{\"row\": 4, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-27.40\", \"Category\": \"Food & Drink\", \"Post Date\": \"09/19/2026\", \"Description\": \"PANERA BREAD #4521\", \"Transaction Date\": \"09/18/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(4,2,'FILE','39f04ddd381e45e11942ff4ffe50eb715917be4a8f39c8c03a4779b226c3b565','2026-09-16',-46.18,'STAPLES 00123',NULL,'Office & Shipping','POSTED',18,NULL,8,NULL,NULL,47,NULL,'{\"row\": 5, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-46.18\", \"Category\": \"Office & Shipping\", \"Post Date\": \"09/16/2026\", \"Description\": \"STAPLES 00123\", \"Transaction Date\": \"09/15/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(5,2,'FILE','e67311327eaa63132cf6a04f8599b3d79971d4fd6c6738014769fcfc184ba0cc','2026-09-13',-18.75,'BLUE BOTTLE COFFEE',NULL,'Food & Drink','POSTED',17,NULL,7,NULL,NULL,46,NULL,'{\"row\": 6, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-18.75\", \"Category\": \"Food & Drink\", \"Post Date\": \"09/13/2026\", \"Description\": \"BLUE BOTTLE COFFEE\", \"Transaction Date\": \"09/12/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(6,2,'FILE','29b1fd43226ff074219b5ce4dbaa9de91681622dceab84434ce0f525b04a1d30','2026-09-11',-15.99,'ZOOM.US 888-799-9666',NULL,'Professional Services','POSTED',14,NULL,6,NULL,NULL,45,NULL,'{\"row\": 7, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-15.99\", \"Category\": \"Professional Services\", \"Post Date\": \"09/11/2026\", \"Description\": \"ZOOM.US 888-799-9666\", \"Transaction Date\": \"09/10/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(7,2,'FILE','52a7bf9bd6753a6bb3d0a3c73b9ffdb86b4e8f767bd8a787f9a4c4619dd72420','2026-09-09',-85.00,'VERIZON WIRELESS',NULL,'Bills & Utilities','POSTED',15,NULL,5,NULL,NULL,44,NULL,'{\"row\": 8, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-85.00\", \"Category\": \"Bills & Utilities\", \"Post Date\": \"09/09/2026\", \"Description\": \"VERIZON WIRELESS\", \"Transaction Date\": \"09/08/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(8,2,'FILE','a417cd880ff2aa4e4a06114fd99d5d227eb8143932ba3d1dad6c720eddb391f9','2026-09-06',-24.00,'DIGITALOCEAN.COM',NULL,'Professional Services','POSTED',13,NULL,4,NULL,NULL,43,NULL,'{\"row\": 9, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-24.00\", \"Category\": \"Professional Services\", \"Post Date\": \"09/06/2026\", \"Description\": \"DIGITALOCEAN.COM\", \"Transaction Date\": \"09/05/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(9,2,'FILE','7ccf4bdc064f6366f15700bacf71e17215b6110756466b85f94aeb0d4dcc4835','2026-09-05',-150.00,'FACEBOOK *ADS 7PQ2',NULL,'Professional Services','POSTED',NULL,NULL,NULL,NULL,NULL,42,NULL,'{\"row\": 10, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-150.00\", \"Category\": \"Professional Services\", \"Post Date\": \"09/05/2026\", \"Description\": \"FACEBOOK *ADS 7PQ2\", \"Transaction Date\": \"09/04/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(10,2,'FILE','160c3eeafaf8f71ebf4ee24c9ce05326aca83947df53181729a380337ed7f152','2026-09-04',-14.40,'GOOGLE *WORKSPACE BLUEB',NULL,'Professional Services','POSTED',14,NULL,3,NULL,NULL,41,NULL,'{\"row\": 11, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-14.40\", \"Category\": \"Professional Services\", \"Post Date\": \"09/04/2026\", \"Description\": \"GOOGLE *WORKSPACE BLUEB\", \"Transaction Date\": \"09/03/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(11,2,'FILE','da35f3e37f6ba3e7672dd74caa6ab1d4d473eecf0554a20b299faa831f67c8a5','2026-09-02',-59.99,'ADOBE *CREATIVE CLD',NULL,'Shopping','POSTED',14,NULL,2,NULL,NULL,40,NULL,'{\"row\": 12, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-59.99\", \"Category\": \"Shopping\", \"Post Date\": \"09/02/2026\", \"Description\": \"ADOBE *CREATIVE CLD\", \"Transaction Date\": \"09/01/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(12,2,'FILE','941cc0310f60b37d6ac76330c46612a1d3f4d84f1de25a1bdfb218ca73c57dbb','2026-08-21',1385.14,'AUTOMATIC PAYMENT - THANK',NULL,'Payment','POSTED',NULL,NULL,NULL,NULL,40,35,NULL,'{\"row\": 13, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Payment\", \"Amount\": \"1385.14\", \"Category\": \"\", \"Post Date\": \"08/21/2026\", \"Description\": \"AUTOMATIC PAYMENT - THANK\", \"Transaction Date\": \"08/20/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','TRANSFER'),(13,2,'FILE','4ea7abe6061e74756550e10e3544d1d863bc9150f6b24b36d9484ed5505672c1','2026-08-19',-27.40,'PANERA BREAD #4521',NULL,'Food & Drink','POSTED',17,NULL,9,NULL,NULL,34,NULL,'{\"row\": 14, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-27.40\", \"Category\": \"Food & Drink\", \"Post Date\": \"08/19/2026\", \"Description\": \"PANERA BREAD #4521\", \"Transaction Date\": \"08/18/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(14,2,'FILE','583db5006791d53cf723578d52054b89751ea1c76d2a715b198455acfe5a2299','2026-08-16',-46.18,'STAPLES 00123',NULL,'Office & Shipping','POSTED',18,NULL,8,NULL,NULL,32,NULL,'{\"row\": 15, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-46.18\", \"Category\": \"Office & Shipping\", \"Post Date\": \"08/16/2026\", \"Description\": \"STAPLES 00123\", \"Transaction Date\": \"08/15/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(15,2,'FILE','282a0d640380b957026a36bc934eab4320efd8145e05a361c28736b7d39cfa37','2026-08-13',-18.75,'BLUE BOTTLE COFFEE',NULL,'Food & Drink','POSTED',17,NULL,7,NULL,NULL,30,NULL,'{\"row\": 16, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-18.75\", \"Category\": \"Food & Drink\", \"Post Date\": \"08/13/2026\", \"Description\": \"BLUE BOTTLE COFFEE\", \"Transaction Date\": \"08/12/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(16,2,'FILE','35c739c728f0f1d335120b42f0f251369e33fce32d5d486ff803d220514f9f33','2026-08-11',-15.99,'ZOOM.US 888-799-9666',NULL,'Professional Services','POSTED',14,NULL,6,NULL,NULL,29,NULL,'{\"row\": 17, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-15.99\", \"Category\": \"Professional Services\", \"Post Date\": \"08/11/2026\", \"Description\": \"ZOOM.US 888-799-9666\", \"Transaction Date\": \"08/10/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(17,2,'FILE','f910731312a6a450792ebfe4d0d76b8cb095e594ab4f7a31d27511e188322996','2026-08-10',-389.12,'HILTON HOTELS CHICAGO',NULL,'Travel','POSTED',NULL,NULL,NULL,NULL,NULL,28,NULL,'{\"row\": 18, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-389.12\", \"Category\": \"Travel\", \"Post Date\": \"08/10/2026\", \"Description\": \"HILTON HOTELS CHICAGO\", \"Transaction Date\": \"08/09/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(18,2,'FILE','7096eb7a14e2e74e14651c2857a72f92452a6a49bc9be834689abdf4a79e942d','2026-08-09',-85.00,'VERIZON WIRELESS',NULL,'Bills & Utilities','POSTED',15,NULL,5,NULL,NULL,27,NULL,'{\"row\": 19, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-85.00\", \"Category\": \"Bills & Utilities\", \"Post Date\": \"08/09/2026\", \"Description\": \"VERIZON WIRELESS\", \"Transaction Date\": \"08/08/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(19,2,'FILE','cc6181dd8668d4674cedb265aa700817d4c2aea7736db68c9af73b4f4960bd0f','2026-08-08',-412.60,'UNITED 0162345678901',NULL,'Travel','POSTED',NULL,NULL,NULL,NULL,NULL,26,NULL,'{\"row\": 20, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-412.60\", \"Category\": \"Travel\", \"Post Date\": \"08/08/2026\", \"Description\": \"UNITED 0162345678901\", \"Transaction Date\": \"08/07/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(20,2,'FILE','39131a98638166823e75e688a790e25939c26027a0b6a20a951daafb42d72c5d','2026-08-06',-24.00,'DIGITALOCEAN.COM',NULL,'Professional Services','POSTED',13,NULL,4,NULL,NULL,25,NULL,'{\"row\": 21, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-24.00\", \"Category\": \"Professional Services\", \"Post Date\": \"08/06/2026\", \"Description\": \"DIGITALOCEAN.COM\", \"Transaction Date\": \"08/05/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(21,2,'FILE','61628351dbecc24ecc4979ccb5e363fa34d30681e9f0c4a3d98e2d1f535404e8','2026-08-04',-14.40,'GOOGLE *WORKSPACE BLUEB',NULL,'Professional Services','POSTED',14,NULL,3,NULL,NULL,24,NULL,'{\"row\": 22, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-14.40\", \"Category\": \"Professional Services\", \"Post Date\": \"08/04/2026\", \"Description\": \"GOOGLE *WORKSPACE BLUEB\", \"Transaction Date\": \"08/03/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(22,2,'FILE','1becc5053dcf6646e74a224402a9395a43ee006e89cee2147ec3d742a62582e0','2026-08-02',-59.99,'ADOBE *CREATIVE CLD',NULL,'Shopping','POSTED',14,NULL,2,NULL,NULL,23,NULL,'{\"row\": 23, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-59.99\", \"Category\": \"Shopping\", \"Post Date\": \"08/02/2026\", \"Description\": \"ADOBE *CREATIVE CLD\", \"Transaction Date\": \"08/01/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781','RULE'),(23,2,'FILE','9613113620c046bbd732de4c9f92411b114879a9f50e2208194d6ec1e771af4a','2026-07-19',-27.40,'PANERA BREAD #4521',NULL,'Food & Drink','POSTED',NULL,NULL,NULL,NULL,NULL,18,NULL,'{\"row\": 24, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-27.40\", \"Category\": \"Food & Drink\", \"Post Date\": \"07/19/2026\", \"Description\": \"PANERA BREAD #4521\", \"Transaction Date\": \"07/18/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(24,2,'FILE','99e0d158a6921694f23edd2db69a319e583496d0a9dfa6ddd065688799ba5041','2026-07-16',-46.18,'STAPLES 00123',NULL,'Office & Shipping','POSTED',NULL,NULL,NULL,NULL,NULL,16,NULL,'{\"row\": 25, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-46.18\", \"Category\": \"Office & Shipping\", \"Post Date\": \"07/16/2026\", \"Description\": \"STAPLES 00123\", \"Transaction Date\": \"07/15/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(25,2,'FILE','3ddf131a7b65438917380ffb0eb28ad082965a3c120b53f74804f53be3caab04','2026-07-13',-18.75,'BLUE BOTTLE COFFEE',NULL,'Food & Drink','POSTED',NULL,NULL,NULL,NULL,NULL,15,NULL,'{\"row\": 26, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-18.75\", \"Category\": \"Food & Drink\", \"Post Date\": \"07/13/2026\", \"Description\": \"BLUE BOTTLE COFFEE\", \"Transaction Date\": \"07/12/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(26,2,'FILE','735393a133e955a100aa99674524dda94b13a3bb8854b7dbd9e211b79540e85e','2026-07-11',-15.99,'ZOOM.US 888-799-9666',NULL,'Professional Services','POSTED',NULL,NULL,NULL,NULL,NULL,14,NULL,'{\"row\": 27, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-15.99\", \"Category\": \"Professional Services\", \"Post Date\": \"07/11/2026\", \"Description\": \"ZOOM.US 888-799-9666\", \"Transaction Date\": \"07/10/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(27,2,'FILE','f684704ae1578a7f97cdd8c7b5f9f42676baedbfbfab8f3a0fa723bc5941a094','2026-07-09',-85.00,'VERIZON WIRELESS',NULL,'Bills & Utilities','POSTED',NULL,NULL,NULL,NULL,NULL,13,NULL,'{\"row\": 28, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-85.00\", \"Category\": \"Bills & Utilities\", \"Post Date\": \"07/09/2026\", \"Description\": \"VERIZON WIRELESS\", \"Transaction Date\": \"07/08/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(28,2,'FILE','b9eb833b6a1c3eb7d2f136f524a698be0acd171d5907be6b9e434db61da682b1','2026-07-06',-24.00,'DIGITALOCEAN.COM',NULL,'Professional Services','POSTED',NULL,NULL,NULL,NULL,NULL,12,NULL,'{\"row\": 29, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-24.00\", \"Category\": \"Professional Services\", \"Post Date\": \"07/06/2026\", \"Description\": \"DIGITALOCEAN.COM\", \"Transaction Date\": \"07/05/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(29,2,'FILE','cdd7d440e8815851cf5259113b4b0b9dfa820da739553ca90d960eb432e62bd7','2026-07-04',-14.40,'GOOGLE *WORKSPACE BLUEB',NULL,'Professional Services','POSTED',NULL,NULL,NULL,NULL,NULL,11,NULL,'{\"row\": 30, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-14.40\", \"Category\": \"Professional Services\", \"Post Date\": \"07/04/2026\", \"Description\": \"GOOGLE *WORKSPACE BLUEB\", \"Transaction Date\": \"07/03/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(30,2,'FILE','d5155d34ed38ff8d14961db542b02d0836d7172291ff4b0e35968fcc897e573f','2026-07-02',-59.99,'ADOBE *CREATIVE CLD',NULL,'Shopping','POSTED',NULL,NULL,NULL,NULL,NULL,10,NULL,'{\"row\": 31, \"file\": \"demo-card.csv\", \"fields\": {\"Memo\": \"\", \"Type\": \"Sale\", \"Amount\": \"-59.99\", \"Category\": \"Shopping\", \"Post Date\": \"07/02/2026\", \"Description\": \"ADOBE *CREATIVE CLD\", \"Transaction Date\": \"07/01/2026\"}, \"layout\": \"CHASE_CARD\"}','2026-10-01 19:34:46.460781',NULL),(31,1,'FILE','5977d0ba9ccb11be97d319fc7ffb615ca9c08b2840f8113e038993d5c2761e9a','2026-09-27',-15.00,'MONTHLY SERVICE FEE',NULL,'FEE_TRANSACTION','SUGGESTED',11,NULL,11,NULL,NULL,NULL,NULL,'{\"row\": 2, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"FEE_TRANSACTION\", \"Amount\": \"-15.00\", \"Balance\": \"11830.65\", \"Details\": \"DEBIT\", \"Description\": \"MONTHLY SERVICE FEE\", \"Posting Date\": \"09/27/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','RULE'),(32,1,'FILE','0a68f3e98a8728c94b8a73f54448a39e07f6493c970d78cf1ed7e0491b7b6289','2026-09-25',-2000.00,'Online Transfer to CHK ...9999 transaction#: 00001',NULL,'ACCT_XFER','SUGGESTED',6,NULL,10,NULL,NULL,NULL,NULL,'{\"row\": 3, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACCT_XFER\", \"Amount\": \"-2000.00\", \"Balance\": \"11845.65\", \"Details\": \"DEBIT\", \"Description\": \"Online Transfer to CHK ...9999 transaction#: 00001\", \"Posting Date\": \"09/25/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','RULE'),(33,1,'FILE','630be9112f3f8876f6e1116007a5c3c31ae7e37330ff8362b215ab96735c15af','2026-09-24',382.50,'Zelle payment from RIVERSIDE BAKERY INV-1007 9X0007',NULL,'PARTNERFI_TO_CHASE','SUGGESTED',NULL,2,NULL,7,NULL,NULL,NULL,'{\"row\": 4, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"PARTNERFI_TO_CHASE\", \"Amount\": \"382.50\", \"Balance\": \"13845.65\", \"Details\": \"CREDIT\", \"Description\": \"Zelle payment from RIVERSIDE BAKERY INV-1007 9X0007\", \"Posting Date\": \"09/24/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','INVOICE'),(34,1,'FILE','245398933dd4d953583ce57e800f51407df6b2d965973470fcd6544b565e4cda','2026-09-21',-441.71,'Payment to Chase card ending in 5678 09/21',NULL,'ACCT_XFER','SUGGESTED',NULL,NULL,NULL,NULL,2,NULL,NULL,'{\"row\": 5, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACCT_XFER\", \"Amount\": \"-441.71\", \"Balance\": \"13463.15\", \"Details\": \"DEBIT\", \"Description\": \"Payment to Chase card ending in 5678 09/21\", \"Posting Date\": \"09/21/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','TRANSFER'),(35,1,'FILE','468e305e8a78f95a6377126220f077e24a2c1e0191426898c9dd226d6e8d4c65','2026-09-17',1500.00,'Zelle payment from ACME DENTAL GROUP INV-1006 9X0006',NULL,'PARTNERFI_TO_CHASE','POSTED',NULL,1,NULL,6,NULL,48,NULL,'{\"row\": 6, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"PARTNERFI_TO_CHASE\", \"Amount\": \"1500.00\", \"Balance\": \"13904.86\", \"Details\": \"CREDIT\", \"Description\": \"Zelle payment from ACME DENTAL GROUP INV-1006 9X0006\", \"Posting Date\": \"09/17/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','INVOICE'),(36,1,'FILE','e75f54e9cc3add701e0ba06170fceaa080eb16a5e74d7972dee4feb9f08a549c','2026-09-01',500.00,'REMOTE ONLINE DEPOSIT # 1',NULL,'CHECK_DEPOSIT','POSTED',NULL,4,NULL,5,NULL,38,NULL,'{\"row\": 7, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"CHECK_DEPOSIT\", \"Amount\": \"500.00\", \"Balance\": \"12404.86\", \"Details\": \"CREDIT\", \"Description\": \"REMOTE ONLINE DEPOSIT # 1\", \"Posting Date\": \"09/01/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','INVOICE_AMOUNT'),(37,1,'FILE','09ed950aa8ddfa98c23f040746c10c9eb687f040e7eed19bf13c058449a8684f','2026-09-01',-1450.00,'ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD',NULL,'ACH_DEBIT','POSTED',24,NULL,1,NULL,NULL,39,NULL,'{\"row\": 8, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACH_DEBIT\", \"Amount\": \"-1450.00\", \"Balance\": \"11904.86\", \"Details\": \"DEBIT\", \"Description\": \"ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD\", \"Posting Date\": \"09/01/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','RULE'),(38,1,'FILE','a09aec9278fcf5e5fa00b9be44d7987d3dad702d774bddc693b1463a6b6b13a4','2026-08-27',-15.00,'MONTHLY SERVICE FEE',NULL,'FEE_TRANSACTION','POSTED',11,NULL,11,NULL,NULL,37,NULL,'{\"row\": 9, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"FEE_TRANSACTION\", \"Amount\": \"-15.00\", \"Balance\": \"13354.86\", \"Details\": \"DEBIT\", \"Description\": \"MONTHLY SERVICE FEE\", \"Posting Date\": \"08/27/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','RULE'),(39,1,'FILE','4b1ea0a0f630a41b07f48f41e842d1cf260f4d8798a2fb6ec18259034cb6baf6','2026-08-25',-2000.00,'Online Transfer to CHK ...9999 transaction#: 00001',NULL,'ACCT_XFER','POSTED',6,NULL,10,NULL,NULL,36,NULL,'{\"row\": 10, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACCT_XFER\", \"Amount\": \"-2000.00\", \"Balance\": \"13369.86\", \"Details\": \"DEBIT\", \"Description\": \"Online Transfer to CHK ...9999 transaction#: 00001\", \"Posting Date\": \"08/25/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','RULE'),(40,1,'FILE','3d203ed72b95b57e259ecc869ab1505dce2f5764284001805f3f84980e9b0f91','2026-08-21',-1385.14,'Payment to Chase card ending in 5678 08/21',NULL,'ACCT_XFER','POSTED',NULL,NULL,NULL,NULL,12,35,NULL,'{\"row\": 11, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACCT_XFER\", \"Amount\": \"-1385.14\", \"Balance\": \"15369.86\", \"Details\": \"DEBIT\", \"Description\": \"Payment to Chase card ending in 5678 08/21\", \"Posting Date\": \"08/21/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','TRANSFER'),(41,1,'FILE','1032e4dea32863d58c8631f6597cb59858a16efdfd8f900aff9ad7a0065db04d','2026-08-17',1500.00,'Zelle payment from ACME DENTAL GROUP INV-1003 9X0003',NULL,'PARTNERFI_TO_CHASE','POSTED',NULL,1,NULL,3,NULL,33,NULL,'{\"row\": 12, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"PARTNERFI_TO_CHASE\", \"Amount\": \"1500.00\", \"Balance\": \"16755.00\", \"Details\": \"CREDIT\", \"Description\": \"Zelle payment from ACME DENTAL GROUP INV-1003 9X0003\", \"Posting Date\": \"08/17/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','INVOICE'),(42,1,'FILE','ce4e57224f5bd5192d5e9bdd3028857e91c91e1d585ab0774814113c18baa726','2026-08-14',-350.00,'CHECK 1001',NULL,'CHECK_PAID','POSTED',NULL,NULL,NULL,NULL,NULL,31,NULL,'{\"row\": 13, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"CHECK_PAID\", \"Amount\": \"-350.00\", \"Balance\": \"15255.00\", \"Details\": \"CHECK\", \"Description\": \"CHECK 1001\", \"Posting Date\": \"08/14/2026\", \"Check or Slip #\": \"1001\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237',NULL),(43,1,'FILE','c52bb2edb260107235be1770e53daf54f7a044d43a56a9a5f24656470992d707','2026-08-01',-1450.00,'ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD',NULL,'ACH_DEBIT','POSTED',24,NULL,1,NULL,NULL,22,NULL,'{\"row\": 14, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACH_DEBIT\", \"Amount\": \"-1450.00\", \"Balance\": \"15605.00\", \"Details\": \"DEBIT\", \"Description\": \"ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD\", \"Posting Date\": \"08/01/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','RULE'),(44,1,'FILE','033ac518603b9bedc3dce41131072590629145d0c4b59b5bd7be32b6b3b6090f','2026-07-27',-15.00,'MONTHLY SERVICE FEE',NULL,'FEE_TRANSACTION','POSTED',NULL,NULL,NULL,NULL,NULL,21,NULL,'{\"row\": 15, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"FEE_TRANSACTION\", \"Amount\": \"-15.00\", \"Balance\": \"17055.00\", \"Details\": \"DEBIT\", \"Description\": \"MONTHLY SERVICE FEE\", \"Posting Date\": \"07/27/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237',NULL),(45,1,'FILE','e77f40ab95e7f5effea2aa7f6f10174129556c87a3b0545f069a91f5bd3facf2','2026-07-25',-2000.00,'Online Transfer to CHK ...9999 transaction#: 00001',NULL,'ACCT_XFER','POSTED',NULL,NULL,NULL,NULL,NULL,20,NULL,'{\"row\": 16, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACCT_XFER\", \"Amount\": \"-2000.00\", \"Balance\": \"17070.00\", \"Details\": \"DEBIT\", \"Description\": \"Online Transfer to CHK ...9999 transaction#: 00001\", \"Posting Date\": \"07/25/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237',NULL),(46,1,'FILE','e8f092a5e6092361f754c2d339434b543cfa425508df4ecf4221541ba1018da7','2026-07-20',1020.00,'Zelle payment from RIVERSIDE BAKERY INV-1002 9X0002',NULL,'PARTNERFI_TO_CHASE','POSTED',NULL,2,NULL,2,NULL,19,NULL,'{\"row\": 17, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"PARTNERFI_TO_CHASE\", \"Amount\": \"1020.00\", \"Balance\": \"19070.00\", \"Details\": \"CREDIT\", \"Description\": \"Zelle payment from RIVERSIDE BAKERY INV-1002 9X0002\", \"Posting Date\": \"07/20/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','INVOICE'),(47,1,'FILE','f2e159e7d93d666c5f6a5e1a41d293bd4edf65ec0f26fc23292f1b8ade9efb16','2026-07-17',1500.00,'Zelle payment from ACME DENTAL GROUP INV-1001 9X0001',NULL,'PARTNERFI_TO_CHASE','POSTED',NULL,1,NULL,1,NULL,17,NULL,'{\"row\": 18, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"PARTNERFI_TO_CHASE\", \"Amount\": \"1500.00\", \"Balance\": \"18050.00\", \"Details\": \"CREDIT\", \"Description\": \"Zelle payment from ACME DENTAL GROUP INV-1001 9X0001\", \"Posting Date\": \"07/17/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237','INVOICE'),(48,1,'FILE','b48a9af98b8c16057ae8133edd13734c88e02310300c1935fc27535e5b90b053','2026-07-01',-1450.00,'ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD',NULL,'ACH_DEBIT','POSTED',NULL,NULL,NULL,NULL,NULL,9,NULL,'{\"row\": 19, \"file\": \"demo-checking.csv\", \"fields\": {\"Type\": \"ACH_DEBIT\", \"Amount\": \"-1450.00\", \"Balance\": \"16550.00\", \"Details\": \"DEBIT\", \"Description\": \"ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD\", \"Posting Date\": \"07/01/2026\", \"Check or Slip #\": \"\"}, \"layout\": \"CHASE_CHECKING\"}','2026-10-01 19:34:46.629237',NULL);
/*!40000 ALTER TABLE `bank_txn` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `invoice`
--

DROP TABLE IF EXISTS `invoice`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `invoice` (
  `id` int NOT NULL AUTO_INCREMENT,
  `number` varchar(20) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `customer_id` int NOT NULL,
  `issue_date` date NOT NULL,
  `due_date` date NOT NULL,
  `terms` varchar(40) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `status` enum('DRAFT','OPEN','PAID','VOID') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'DRAFT',
  `total` decimal(14,2) NOT NULL DEFAULT '0.00',
  `amount_paid` decimal(14,2) NOT NULL DEFAULT '0.00',
  `paid_on` date DEFAULT NULL,
  `memo` text COLLATE utf8mb4_unicode_ci,
  `source` enum('LEDGER','QBO') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'LEDGER',
  `entry_id` bigint DEFAULT NULL,
  `pdf_path` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `email_requested_at` datetime(6) DEFAULT NULL,
  `emailed_at` datetime(6) DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_invoice_number` (`number`),
  KEY `entry_id` (`entry_id`),
  KEY `ix_invoice_customer` (`customer_id`,`issue_date`),
  KEY `ix_invoice_status` (`status`,`due_date`),
  CONSTRAINT `invoice_ibfk_1` FOREIGN KEY (`customer_id`) REFERENCES `payee` (`id`),
  CONSTRAINT `invoice_ibfk_2` FOREIGN KEY (`entry_id`) REFERENCES `journal_entry` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=9 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `invoice`
--

LOCK TABLES `invoice` WRITE;
/*!40000 ALTER TABLE `invoice` DISABLE KEYS */;
INSERT INTO `invoice` VALUES (1,'INV-1001',1,'2026-07-05','2026-07-20',NULL,'PAID',1500.00,1500.00,'2026-07-17',NULL,'LEDGER',2,'invoices/INV-1001.pdf',NULL,NULL),(2,'INV-1002',2,'2026-07-08','2026-07-23',NULL,'PAID',1020.00,1020.00,'2026-07-20',NULL,'LEDGER',3,'invoices/INV-1002.pdf',NULL,NULL),(3,'INV-1003',1,'2026-08-05','2026-08-20',NULL,'PAID',1500.00,1500.00,'2026-08-17',NULL,'LEDGER',4,'invoices/INV-1003.pdf',NULL,NULL),(4,'INV-1004',3,'2026-08-09','2026-08-24',NULL,'OPEN',2400.00,0.00,NULL,NULL,'LEDGER',5,'invoices/INV-1004.pdf',NULL,NULL),(5,'INV-1005',4,'2026-08-20','2026-09-04',NULL,'PAID',500.00,500.00,'2026-09-01',NULL,'LEDGER',6,'invoices/INV-1005.pdf',NULL,NULL),(6,'INV-1006',1,'2026-09-05','2026-09-20',NULL,'PAID',1500.00,1500.00,'2026-09-17',NULL,'LEDGER',7,'invoices/INV-1006.pdf',NULL,NULL),(7,'INV-1007',2,'2026-09-12','2026-09-27',NULL,'OPEN',382.50,0.00,NULL,NULL,'LEDGER',8,'invoices/INV-1007.pdf',NULL,NULL),(8,NULL,4,'2026-10-01','2026-10-16',NULL,'DRAFT',360.00,0.00,NULL,NULL,'LEDGER',NULL,NULL,NULL,NULL);
/*!40000 ALTER TABLE `invoice` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `invoice_line`
--

DROP TABLE IF EXISTS `invoice_line`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `invoice_line` (
  `id` int NOT NULL AUTO_INCREMENT,
  `invoice_id` int NOT NULL,
  `line_no` smallint NOT NULL,
  `description` varchar(255) COLLATE utf8mb4_unicode_ci NOT NULL,
  `quantity` decimal(10,2) NOT NULL DEFAULT '1.00',
  `rate` decimal(14,2) NOT NULL,
  `amount` decimal(14,2) NOT NULL,
  `income_account_id` int NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_invoice_line` (`invoice_id`,`line_no`),
  KEY `income_account_id` (`income_account_id`),
  CONSTRAINT `invoice_line_ibfk_1` FOREIGN KEY (`invoice_id`) REFERENCES `invoice` (`id`),
  CONSTRAINT `invoice_line_ibfk_2` FOREIGN KEY (`income_account_id`) REFERENCES `account` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=10 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `invoice_line`
--

LOCK TABLES `invoice_line` WRITE;
/*!40000 ALTER TABLE `invoice_line` DISABLE KEYS */;
INSERT INTO `invoice_line` VALUES (1,1,1,'Monthly design retainer',1.00,1500.00,1500.00,8),(2,2,1,'Menu and signage design',12.00,85.00,1020.00,8),(3,3,1,'Monthly design retainer',1.00,1500.00,1500.00,8),(4,4,1,'Website redesign - phase 1',1.00,2400.00,2400.00,8),(5,5,1,'Class schedule poster',6.00,75.00,450.00,8),(6,5,2,'Print-ready files',1.00,50.00,50.00,8),(7,6,1,'Monthly design retainer',1.00,1500.00,1500.00,8),(8,7,1,'Seasonal menu update',4.50,85.00,382.50,8),(9,8,1,'Monthly social media graphics',8.00,45.00,360.00,8);
/*!40000 ALTER TABLE `invoice_line` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `invoice_payment`
--

DROP TABLE IF EXISTS `invoice_payment`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `invoice_payment` (
  `id` int NOT NULL AUTO_INCREMENT,
  `invoice_id` int NOT NULL,
  `entry_id` bigint DEFAULT NULL,
  `paid_on` date NOT NULL,
  `amount` decimal(14,2) NOT NULL,
  `source` enum('LEDGER','QBO_DERIVED') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'LEDGER',
  PRIMARY KEY (`id`),
  KEY `entry_id` (`entry_id`),
  KEY `ix_invoice_payment_invoice` (`invoice_id`),
  CONSTRAINT `invoice_payment_ibfk_1` FOREIGN KEY (`invoice_id`) REFERENCES `invoice` (`id`),
  CONSTRAINT `invoice_payment_ibfk_2` FOREIGN KEY (`entry_id`) REFERENCES `journal_entry` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=6 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `invoice_payment`
--

LOCK TABLES `invoice_payment` WRITE;
/*!40000 ALTER TABLE `invoice_payment` DISABLE KEYS */;
INSERT INTO `invoice_payment` VALUES (1,1,17,'2026-07-17',1500.00,'LEDGER'),(2,2,19,'2026-07-20',1020.00,'LEDGER'),(3,3,33,'2026-08-17',1500.00,'LEDGER'),(4,5,38,'2026-09-01',500.00,'LEDGER'),(5,6,48,'2026-09-17',1500.00,'LEDGER');
/*!40000 ALTER TABLE `invoice_payment` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `journal_entry`
--

DROP TABLE IF EXISTS `journal_entry`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `journal_entry` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `entry_date` date NOT NULL,
  `memo` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `source` enum('MANUAL','BANK','INVOICE','PAYMENT','OPENING','REVERSAL','IMPORT') COLLATE utf8mb4_unicode_ci NOT NULL,
  `payee_id` int DEFAULT NULL,
  `reverses_entry_id` bigint DEFAULT NULL,
  `reversed_by_entry_id` bigint DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  KEY `payee_id` (`payee_id`),
  KEY `reverses_entry_id` (`reverses_entry_id`),
  KEY `reversed_by_entry_id` (`reversed_by_entry_id`),
  KEY `ix_entry_date` (`entry_date`),
  CONSTRAINT `journal_entry_ibfk_1` FOREIGN KEY (`payee_id`) REFERENCES `payee` (`id`),
  CONSTRAINT `journal_entry_ibfk_2` FOREIGN KEY (`reverses_entry_id`) REFERENCES `journal_entry` (`id`),
  CONSTRAINT `journal_entry_ibfk_3` FOREIGN KEY (`reversed_by_entry_id`) REFERENCES `journal_entry` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=49 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `journal_entry`
--

LOCK TABLES `journal_entry` WRITE;
/*!40000 ALTER TABLE `journal_entry` DISABLE KEYS */;
INSERT INTO `journal_entry` VALUES (1,'2026-06-30','Opening balance','OPENING',NULL,NULL,NULL,'2026-10-01 19:34:44.758479'),(2,'2026-07-05','Invoice INV-1001 - Acme Dental Group','INVOICE',1,NULL,NULL,'2026-10-01 19:34:45.739949'),(3,'2026-07-08','Invoice INV-1002 - Riverside Bakery','INVOICE',2,NULL,NULL,'2026-10-01 19:34:45.847126'),(4,'2026-08-05','Invoice INV-1003 - Acme Dental Group','INVOICE',1,NULL,NULL,'2026-10-01 19:34:45.957422'),(5,'2026-08-09','Invoice INV-1004 - Harbor Law Partners','INVOICE',3,NULL,NULL,'2026-10-01 19:34:46.060779'),(6,'2026-08-20','Invoice INV-1005 - Summit Fitness','INVOICE',4,NULL,NULL,'2026-10-01 19:34:46.161864'),(7,'2026-09-05','Invoice INV-1006 - Acme Dental Group','INVOICE',1,NULL,NULL,'2026-10-01 19:34:46.264151'),(8,'2026-09-12','Invoice INV-1007 - Riverside Bakery','INVOICE',2,NULL,NULL,'2026-10-01 19:34:46.364096'),(9,'2026-07-01','ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD','BANK',NULL,NULL,NULL,'2026-10-01 19:34:46.791142'),(10,'2026-07-02','ADOBE *CREATIVE CLD','BANK',NULL,NULL,NULL,'2026-10-01 19:34:46.925976'),(11,'2026-07-04','GOOGLE *WORKSPACE BLUEB','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.052314'),(12,'2026-07-06','DIGITALOCEAN.COM','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.181304'),(13,'2026-07-09','VERIZON WIRELESS','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.303978'),(14,'2026-07-11','ZOOM.US 888-799-9666','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.416340'),(15,'2026-07-13','BLUE BOTTLE COFFEE','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.538592'),(16,'2026-07-16','STAPLES 00123','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.675429'),(17,'2026-07-17','Payment of invoice INV-1001 - Acme Dental Group','BANK',1,NULL,NULL,'2026-10-01 19:34:47.812748'),(18,'2026-07-19','PANERA BREAD #4521','BANK',NULL,NULL,NULL,'2026-10-01 19:34:47.887857'),(19,'2026-07-20','Payment of invoice INV-1002 - Riverside Bakery','BANK',2,NULL,NULL,'2026-10-01 19:34:48.013588'),(20,'2026-07-25','Online Transfer to CHK ...9999 transaction#: 00001','BANK',NULL,NULL,NULL,'2026-10-01 19:34:48.091596'),(21,'2026-07-27','MONTHLY SERVICE FEE','BANK',NULL,NULL,NULL,'2026-10-01 19:34:48.241912'),(22,'2026-08-01','ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD','BANK',NULL,NULL,NULL,'2026-10-01 19:34:48.418505'),(23,'2026-08-02','ADOBE *CREATIVE CLD','BANK',NULL,NULL,NULL,'2026-10-01 19:34:48.550800'),(24,'2026-08-04','GOOGLE *WORKSPACE BLUEB','BANK',NULL,NULL,NULL,'2026-10-01 19:34:48.721971'),(25,'2026-08-06','DIGITALOCEAN.COM','BANK',NULL,NULL,NULL,'2026-10-01 19:34:48.942041'),(26,'2026-08-08','UNITED 0162345678901','BANK',NULL,NULL,NULL,'2026-10-01 19:34:49.122665'),(27,'2026-08-09','VERIZON WIRELESS','BANK',NULL,NULL,NULL,'2026-10-01 19:34:49.518049'),(28,'2026-08-10','HILTON HOTELS CHICAGO','BANK',NULL,NULL,NULL,'2026-10-01 19:34:49.696840'),(29,'2026-08-11','ZOOM.US 888-799-9666','BANK',NULL,NULL,NULL,'2026-10-01 19:34:50.086663'),(30,'2026-08-13','BLUE BOTTLE COFFEE','BANK',NULL,NULL,NULL,'2026-10-01 19:34:50.271198'),(31,'2026-08-14','CHECK 1001','BANK',NULL,NULL,NULL,'2026-10-01 19:34:50.462220'),(32,'2026-08-16','STAPLES 00123','BANK',NULL,NULL,NULL,'2026-10-01 19:34:50.659721'),(33,'2026-08-17','Payment of invoice INV-1003 - Acme Dental Group','BANK',1,NULL,NULL,'2026-10-01 19:34:50.883592'),(34,'2026-08-19','PANERA BREAD #4521','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.092749'),(35,'2026-08-21','Transfer: Business Checking to Business Card','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.227545'),(36,'2026-08-25','Online Transfer to CHK ...9999 transaction#: 00001','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.358830'),(37,'2026-08-27','MONTHLY SERVICE FEE','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.458936'),(38,'2026-09-01','Payment of invoice INV-1005 - Summit Fitness','BANK',4,NULL,NULL,'2026-10-01 19:34:51.557887'),(39,'2026-09-01','ORIG CO NAME:SUNRISE PROPERTIES ORIG ID:9000000001 DESC DATE: CO ENTRY DESCR:RENT SEC:PPD','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.651520'),(40,'2026-09-02','ADOBE *CREATIVE CLD','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.712023'),(41,'2026-09-04','GOOGLE *WORKSPACE BLUEB','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.784639'),(42,'2026-09-05','FACEBOOK *ADS 7PQ2','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.844688'),(43,'2026-09-06','DIGITALOCEAN.COM','BANK',NULL,NULL,NULL,'2026-10-01 19:34:51.973110'),(44,'2026-09-09','VERIZON WIRELESS','BANK',NULL,NULL,NULL,'2026-10-01 19:34:52.043536'),(45,'2026-09-11','ZOOM.US 888-799-9666','BANK',NULL,NULL,NULL,'2026-10-01 19:34:52.107818'),(46,'2026-09-13','BLUE BOTTLE COFFEE','BANK',NULL,NULL,NULL,'2026-10-01 19:34:52.170568'),(47,'2026-09-16','STAPLES 00123','BANK',NULL,NULL,NULL,'2026-10-01 19:34:52.230713'),(48,'2026-09-17','Payment of invoice INV-1006 - Acme Dental Group','BANK',1,NULL,NULL,'2026-10-01 19:34:52.300919');
/*!40000 ALTER TABLE `journal_entry` ENABLE KEYS */;
UNLOCK TABLES;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`gl`@`%`*/ /*!50003 TRIGGER `trg_journal_entry_before_update` BEFORE UPDATE ON `journal_entry` FOR EACH ROW BEGIN
            IF NOT (NEW.entry_date <=> OLD.entry_date AND NEW.source <=> OLD.source
                    AND NEW.payee_id <=> OLD.payee_id
                    AND NEW.reverses_entry_id <=> OLD.reverses_entry_id
                    AND NEW.created_at <=> OLD.created_at) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_entry: posted entries are immutable; only memo may change';
            END IF;
            IF OLD.reversed_by_entry_id IS NOT NULL
               AND NOT (NEW.reversed_by_entry_id <=> OLD.reversed_by_entry_id) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_entry: a reversal link cannot be changed once set';
            END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`gl`@`%`*/ /*!50003 TRIGGER `trg_journal_entry_before_delete` BEFORE DELETE ON `journal_entry` FOR EACH ROW SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'journal_entry: posted entries are never deleted; post a reversal' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `journal_line`
--

DROP TABLE IF EXISTS `journal_line`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `journal_line` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `entry_id` bigint NOT NULL,
  `line_no` smallint NOT NULL,
  `account_id` int NOT NULL,
  `amount` decimal(14,2) NOT NULL,
  `memo` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `cleared_recon_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_line` (`entry_id`,`line_no`),
  KEY `ix_line_account` (`account_id`,`entry_id`),
  CONSTRAINT `journal_line_ibfk_1` FOREIGN KEY (`entry_id`) REFERENCES `journal_entry` (`id`),
  CONSTRAINT `journal_line_ibfk_2` FOREIGN KEY (`account_id`) REFERENCES `account` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=97 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `journal_line`
--

LOCK TABLES `journal_line` WRITE;
/*!40000 ALTER TABLE `journal_line` DISABLE KEYS */;
INSERT INTO `journal_line` VALUES (1,1,1,1,18000.00,NULL,NULL),(2,1,2,5,-18000.00,NULL,NULL),(3,2,1,2,1500.00,NULL,NULL),(4,2,2,8,-1500.00,NULL,NULL),(5,3,1,2,1020.00,NULL,NULL),(6,3,2,8,-1020.00,NULL,NULL),(7,4,1,2,1500.00,NULL,NULL),(8,4,2,8,-1500.00,NULL,NULL),(9,5,1,2,2400.00,NULL,NULL),(10,5,2,8,-2400.00,NULL,NULL),(11,6,1,2,500.00,NULL,NULL),(12,6,2,8,-500.00,NULL,NULL),(13,7,1,2,1500.00,NULL,NULL),(14,7,2,8,-1500.00,NULL,NULL),(15,8,1,2,382.50,NULL,NULL),(16,8,2,8,-382.50,NULL,NULL),(17,9,1,1,-1450.00,NULL,NULL),(18,9,2,24,1450.00,NULL,NULL),(19,10,1,3,-59.99,NULL,NULL),(20,10,2,14,59.99,NULL,NULL),(21,11,1,3,-14.40,NULL,NULL),(22,11,2,14,14.40,NULL,NULL),(23,12,1,3,-24.00,NULL,NULL),(24,12,2,13,24.00,NULL,NULL),(25,13,1,3,-85.00,NULL,NULL),(26,13,2,15,85.00,NULL,NULL),(27,14,1,3,-15.99,NULL,NULL),(28,14,2,14,15.99,NULL,NULL),(29,15,1,3,-18.75,NULL,NULL),(30,15,2,17,18.75,NULL,NULL),(31,16,1,3,-46.18,NULL,NULL),(32,16,2,18,46.18,NULL,NULL),(33,17,1,1,1500.00,NULL,NULL),(34,17,2,2,-1500.00,'Invoice INV-1001',NULL),(35,18,1,3,-27.40,NULL,NULL),(36,18,2,17,27.40,NULL,NULL),(37,19,1,1,1020.00,NULL,NULL),(38,19,2,2,-1020.00,'Invoice INV-1002',NULL),(39,20,1,1,-2000.00,NULL,NULL),(40,20,2,6,2000.00,NULL,NULL),(41,21,1,1,-15.00,NULL,NULL),(42,21,2,11,15.00,NULL,NULL),(43,22,1,1,-1450.00,NULL,NULL),(44,22,2,24,1450.00,NULL,NULL),(45,23,1,3,-59.99,NULL,NULL),(46,23,2,14,59.99,NULL,NULL),(47,24,1,3,-14.40,NULL,NULL),(48,24,2,14,14.40,NULL,NULL),(49,25,1,3,-24.00,NULL,NULL),(50,25,2,13,24.00,NULL,NULL),(51,26,1,3,-412.60,NULL,NULL),(52,26,2,16,412.60,NULL,NULL),(53,27,1,3,-85.00,NULL,NULL),(54,27,2,15,85.00,NULL,NULL),(55,28,1,3,-389.12,NULL,NULL),(56,28,2,16,389.12,NULL,NULL),(57,29,1,3,-15.99,NULL,NULL),(58,29,2,14,15.99,NULL,NULL),(59,30,1,3,-18.75,NULL,NULL),(60,30,2,17,18.75,NULL,NULL),(61,31,1,1,-350.00,NULL,NULL),(62,31,2,21,350.00,NULL,NULL),(63,32,1,3,-46.18,NULL,NULL),(64,32,2,18,46.18,NULL,NULL),(65,33,1,1,1500.00,NULL,NULL),(66,33,2,2,-1500.00,'Invoice INV-1003',NULL),(67,34,1,3,-27.40,NULL,NULL),(68,34,2,17,27.40,NULL,NULL),(69,35,1,3,1385.14,'AUTOMATIC PAYMENT - THANK',NULL),(70,35,2,1,-1385.14,'Payment to Chase card ending in 5678 08/21',NULL),(71,36,1,1,-2000.00,NULL,NULL),(72,36,2,6,2000.00,NULL,NULL),(73,37,1,1,-15.00,NULL,NULL),(74,37,2,11,15.00,NULL,NULL),(75,38,1,1,500.00,NULL,NULL),(76,38,2,2,-500.00,'Invoice INV-1005',NULL),(77,39,1,1,-1450.00,NULL,NULL),(78,39,2,24,1450.00,NULL,NULL),(79,40,1,3,-59.99,NULL,NULL),(80,40,2,14,59.99,NULL,NULL),(81,41,1,3,-14.40,NULL,NULL),(82,41,2,14,14.40,NULL,NULL),(83,42,1,3,-150.00,NULL,NULL),(84,42,2,10,150.00,NULL,NULL),(85,43,1,3,-24.00,NULL,NULL),(86,43,2,13,24.00,NULL,NULL),(87,44,1,3,-85.00,NULL,NULL),(88,44,2,15,85.00,NULL,NULL),(89,45,1,3,-15.99,NULL,NULL),(90,45,2,14,15.99,NULL,NULL),(91,46,1,3,-18.75,NULL,NULL),(92,46,2,17,18.75,NULL,NULL),(93,47,1,3,-46.18,NULL,NULL),(94,47,2,18,46.18,NULL,NULL),(95,48,1,1,1500.00,NULL,NULL),(96,48,2,2,-1500.00,'Invoice INV-1006',NULL);
/*!40000 ALTER TABLE `journal_line` ENABLE KEYS */;
UNLOCK TABLES;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`gl`@`%`*/ /*!50003 TRIGGER `trg_journal_line_before_insert` BEFORE INSERT ON `journal_line` FOR EACH ROW BEGIN
            IF NEW.amount = 0 THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_line: a line amount cannot be 0.00';
            END IF;
            IF EXISTS (
                SELECT 1 FROM journal_entry e JOIN settings s ON s.id = 1
                WHERE e.id = NEW.entry_id
                  AND s.lock_date IS NOT NULL
                  AND e.entry_date <= s.lock_date
            ) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_line: the entry is dated on or before the lock date';
            END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`gl`@`%`*/ /*!50003 TRIGGER `trg_journal_line_before_update` BEFORE UPDATE ON `journal_line` FOR EACH ROW BEGIN
            IF NOT (NEW.entry_id <=> OLD.entry_id AND NEW.account_id <=> OLD.account_id
                    AND NEW.amount <=> OLD.amount AND NEW.line_no <=> OLD.line_no) THEN
                SIGNAL SQLSTATE '45000'
                    SET MESSAGE_TEXT = 'journal_line: posted lines are immutable; only memo and cleared_recon_id may change';
            END IF;
        END */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;
/*!50003 SET @saved_cs_client      = @@character_set_client */ ;
/*!50003 SET @saved_cs_results     = @@character_set_results */ ;
/*!50003 SET @saved_col_connection = @@collation_connection */ ;
/*!50003 SET character_set_client  = utf8mb4 */ ;
/*!50003 SET character_set_results = utf8mb4 */ ;
/*!50003 SET collation_connection  = utf8mb4_0900_ai_ci */ ;
/*!50003 SET @saved_sql_mode       = @@sql_mode */ ;
/*!50003 SET sql_mode              = 'ONLY_FULL_GROUP_BY,STRICT_TRANS_TABLES,NO_ZERO_IN_DATE,NO_ZERO_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION' */ ;
DELIMITER ;;
/*!50003 CREATE*/ /*!50017 DEFINER=`gl`@`%`*/ /*!50003 TRIGGER `trg_journal_line_before_delete` BEFORE DELETE ON `journal_line` FOR EACH ROW SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'journal_line: posted lines are never deleted; post a reversal' */;;
DELIMITER ;
/*!50003 SET sql_mode              = @saved_sql_mode */ ;
/*!50003 SET character_set_client  = @saved_cs_client */ ;
/*!50003 SET character_set_results = @saved_cs_results */ ;
/*!50003 SET collation_connection  = @saved_col_connection */ ;

--
-- Table structure for table `payee`
--

DROP TABLE IF EXISTS `payee`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `payee` (
  `id` int NOT NULL AUTO_INCREMENT,
  `name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL,
  `is_customer` tinyint(1) NOT NULL DEFAULT '0',
  `is_vendor` tinyint(1) NOT NULL DEFAULT '0',
  `email` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `address` text COLLATE utf8mb4_unicode_ci,
  `default_account_id` int DEFAULT NULL,
  `is_1099_vendor` tinyint(1) NOT NULL DEFAULT '0',
  `tax_id_ref` varchar(60) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `payment_terms_days` int NOT NULL DEFAULT '15',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  `last_used_on` date DEFAULT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uq_payee_name` (`name`),
  KEY `default_account_id` (`default_account_id`),
  KEY `ix_payee_active_name` (`is_active`,`name`),
  CONSTRAINT `payee_ibfk_1` FOREIGN KEY (`default_account_id`) REFERENCES `account` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=5 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `payee`
--

LOCK TABLES `payee` WRITE;
/*!40000 ALTER TABLE `payee` DISABLE KEYS */;
INSERT INTO `payee` VALUES (1,'Acme Dental Group',1,0,'billing@acmedental.example',NULL,NULL,0,NULL,15,1,'2026-09-17'),(2,'Riverside Bakery',1,0,'owner@riversidebakery.example',NULL,NULL,0,NULL,15,1,'2026-09-12'),(3,'Harbor Law Partners',1,0,'accounts@harborlaw.example',NULL,NULL,0,NULL,15,1,'2026-08-09'),(4,'Summit Fitness',1,0,'hello@summitfitness.example',NULL,NULL,0,NULL,15,1,'2026-09-01');
/*!40000 ALTER TABLE `payee` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `payee_rule`
--

DROP TABLE IF EXISTS `payee_rule`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `payee_rule` (
  `id` int NOT NULL AUTO_INCREMENT,
  `priority` int NOT NULL DEFAULT '100',
  `match_field` enum('DESCRIPTION','MERCHANT') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'DESCRIPTION',
  `match_type` enum('CONTAINS','STARTS_WITH','EQUALS','REGEX') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'CONTAINS',
  `pattern` varchar(200) COLLATE utf8mb4_unicode_ci NOT NULL,
  `bank_account_id` int DEFAULT NULL,
  `amount_min` decimal(14,2) DEFAULT NULL,
  `amount_max` decimal(14,2) DEFAULT NULL,
  `payee_id` int DEFAULT NULL,
  `account_id` int DEFAULT NULL,
  `action` enum('SUGGEST','EXCLUDE','TRANSFER') COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT 'SUGGEST',
  `memo_template` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `times_applied` int NOT NULL DEFAULT '0',
  `is_active` tinyint(1) NOT NULL DEFAULT '1',
  PRIMARY KEY (`id`),
  KEY `bank_account_id` (`bank_account_id`),
  KEY `payee_id` (`payee_id`),
  KEY `account_id` (`account_id`),
  CONSTRAINT `payee_rule_ibfk_1` FOREIGN KEY (`bank_account_id`) REFERENCES `bank_account` (`id`),
  CONSTRAINT `payee_rule_ibfk_2` FOREIGN KEY (`payee_id`) REFERENCES `payee` (`id`),
  CONSTRAINT `payee_rule_ibfk_3` FOREIGN KEY (`account_id`) REFERENCES `account` (`id`)
) ENGINE=InnoDB AUTO_INCREMENT=15 DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `payee_rule`
--

LOCK TABLES `payee_rule` WRITE;
/*!40000 ALTER TABLE `payee_rule` DISABLE KEYS */;
INSERT INTO `payee_rule` VALUES (1,100,'DESCRIPTION','CONTAINS','SUNRISE PROPERTIES',1,NULL,NULL,NULL,24,'SUGGEST',NULL,2,1),(2,100,'DESCRIPTION','CONTAINS','ADOBE *CREATIVE CLD',2,NULL,NULL,NULL,14,'SUGGEST',NULL,2,1),(3,100,'DESCRIPTION','CONTAINS','GOOGLE *WORKSPACE BLUEB',2,NULL,NULL,NULL,14,'SUGGEST',NULL,2,1),(4,100,'DESCRIPTION','CONTAINS','DIGITALOCEAN.COM',2,NULL,NULL,NULL,13,'SUGGEST',NULL,2,1),(5,100,'DESCRIPTION','CONTAINS','VERIZON WIRELESS',2,NULL,NULL,NULL,15,'SUGGEST',NULL,2,1),(6,100,'DESCRIPTION','CONTAINS','ZOOM.US',2,NULL,NULL,NULL,14,'SUGGEST',NULL,2,1),(7,100,'DESCRIPTION','CONTAINS','BLUE BOTTLE COFFEE',2,NULL,NULL,NULL,17,'SUGGEST',NULL,2,1),(8,100,'DESCRIPTION','CONTAINS','STAPLES',2,NULL,NULL,NULL,18,'SUGGEST',NULL,2,1),(9,100,'DESCRIPTION','CONTAINS','PANERA BREAD',2,NULL,NULL,NULL,17,'SUGGEST',NULL,1,1),(10,100,'DESCRIPTION','CONTAINS','Online Transfer to',1,NULL,NULL,NULL,6,'SUGGEST',NULL,1,1),(11,100,'DESCRIPTION','CONTAINS','MONTHLY SERVICE FEE',1,NULL,NULL,NULL,11,'SUGGEST',NULL,1,1),(12,100,'DESCRIPTION','CONTAINS','UNITED',2,NULL,NULL,NULL,16,'SUGGEST',NULL,0,1),(13,100,'DESCRIPTION','CONTAINS','HILTON HOTELS CHICAGO',2,NULL,NULL,NULL,16,'SUGGEST',NULL,0,1),(14,100,'DESCRIPTION','CONTAINS','FACEBOOK *ADS',2,NULL,NULL,NULL,10,'SUGGEST',NULL,0,1);
/*!40000 ALTER TABLE `payee_rule` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Table structure for table `settings`
--

DROP TABLE IF EXISTS `settings`;
/*!40101 SET @saved_cs_client     = @@character_set_client */;
/*!50503 SET character_set_client = utf8mb4 */;
CREATE TABLE `settings` (
  `id` smallint NOT NULL,
  `company_name` varchar(120) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `owner_password_hash` varchar(255) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `totp_secret_ref` varchar(60) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `company_address` text COLLATE utf8mb4_unicode_ci,
  `fiscal_year_start_month` smallint NOT NULL DEFAULT '1',
  `lock_date` date DEFAULT NULL,
  `ar_account_id` int NOT NULL,
  `retained_earnings_account_id` int NOT NULL,
  `invoice_prefix` varchar(10) COLLATE utf8mb4_unicode_ci NOT NULL DEFAULT '',
  `next_invoice_seq` int NOT NULL DEFAULT '1',
  `zelle_recipient` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `zelle_display_name` varchar(120) COLLATE utf8mb4_unicode_ci DEFAULT NULL,
  `default_income_account_id` int DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `fk_settings_ar_account` (`ar_account_id`),
  KEY `fk_settings_re_account` (`retained_earnings_account_id`),
  KEY `fk_settings_income_account` (`default_income_account_id`),
  CONSTRAINT `fk_settings_ar_account` FOREIGN KEY (`ar_account_id`) REFERENCES `account` (`id`),
  CONSTRAINT `fk_settings_income_account` FOREIGN KEY (`default_income_account_id`) REFERENCES `account` (`id`),
  CONSTRAINT `fk_settings_re_account` FOREIGN KEY (`retained_earnings_account_id`) REFERENCES `account` (`id`),
  CONSTRAINT `ck_settings_fy_month` CHECK ((`fiscal_year_start_month` between 1 and 12)),
  CONSTRAINT `ck_settings_single_row` CHECK ((`id` = 1))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
/*!40101 SET character_set_client = @saved_cs_client */;

--
-- Dumping data for table `settings`
--

LOCK TABLES `settings` WRITE;
/*!40000 ALTER TABLE `settings` DISABLE KEYS */;
INSERT INTO `settings` VALUES (1,'Bluebird Design Studio LLC','$argon2id$v=19$m=65536,t=3,p=4$AIOTTal/HQV7t1KDIiSyVA$ZmW4v6KalWXX4T56oB/YRsvi/70+c2A0Q6htg51MA+U',NULL,'100 Example Avenue, Suite 2\nSpringfield, IL 62701',1,'2026-07-31',2,7,'INV-',1008,'pay@bluebird.example','Bluebird Design Studio',8);
/*!40000 ALTER TABLE `settings` ENABLE KEYS */;
UNLOCK TABLES;

--
-- Dumping routines for database 'gl'
--
/*!40103 SET TIME_ZONE=@OLD_TIME_ZONE */;

/*!40101 SET SQL_MODE=@OLD_SQL_MODE */;
/*!40014 SET FOREIGN_KEY_CHECKS=@OLD_FOREIGN_KEY_CHECKS */;
/*!40014 SET UNIQUE_CHECKS=@OLD_UNIQUE_CHECKS */;
/*!40101 SET CHARACTER_SET_CLIENT=@OLD_CHARACTER_SET_CLIENT */;
/*!40101 SET CHARACTER_SET_RESULTS=@OLD_CHARACTER_SET_RESULTS */;
/*!40101 SET COLLATION_CONNECTION=@OLD_COLLATION_CONNECTION */;
/*!40111 SET SQL_NOTES=@OLD_SQL_NOTES */;

-- Dump completed on 2026-10-01 19:35:20
-- EOF - docker/dev-initdb/02-demo.sql
