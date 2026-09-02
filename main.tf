# ============================================================
# Terraform / Provider configuration
# ============================================================

terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    bucket         = "music-analytics-tfstate"
    key            = "music-analytics/terraform.tfstate"
    region         = "eu-west-1"
    dynamodb_table = "dynamo-table-music-analytics-tfstate"
  }
}

provider "aws" {
  region = "eu-west-1"
}


# ============================================================
# IAM — Lambda execution role
# ============================================================

resource "aws_iam_role" "lambda_role" {
  name = "lambda_role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Sid    = ""
        Principal = {
          Service = "lambda.amazonaws.com"
        }
      }
    ]
  })
}

resource "aws_iam_role_policy" "lambda_policy" {
  name = "lambda_policy"
  role = aws_iam_role.lambda_role.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "CloudWatchLogs"
        Effect = "Allow"
        Action = [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ]
        Resource = "arn:aws:logs:*:*:*"
      },
      {
        Sid    = "ParameterStoreAccess"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter",
          "ssm:PutParameter"
        ]
        Resource = "arn:aws:ssm:*:*:parameter/music-analytics/*"
      },
      {
        Sid    = "RDSSecretAccess"
        Effect = "Allow"
        Action = [
          "secretsmanager:GetSecretValue"
        ]
        Resource = aws_db_instance.rds_db.master_user_secret[0].secret_arn
      }
    ]
  })
}

# ============================================================
# RDS - Relational Database Service (Postgres DB)
# ============================================================

data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

resource "aws_db_subnet_group" "rds_subnet_group" {
  name       = "music-analytics-subnet-group"
  subnet_ids = data.aws_subnets.default.ids
}

resource "aws_security_group" "rds_security_group" {
  name        = "rds-security-group"
  description = "Allows Postgres access from my IP and Grafana Cloud"
  vpc_id      = data.aws_vpc.default.id
}

resource "aws_vpc_security_group_ingress_rule" "allow_postgres" {
  security_group_id = aws_security_group.rds_security_group.id
  cidr_ipv4         = "79.116.239.17/32" # See ADR 03
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
}

# resource "aws_vpc_security_group_ingress_rule" "allow_grafana" {
#     security_group_id = aws_security_group.rds_security_group.id
#     cidr_ipv4 = "pending" # fetch from Grafana Allowlist API, see ADR 08
#     ip_protocol = "tcp"
#     from_port = 5432
#     to_port = 5432
# }

resource "aws_vpc_security_group_egress_rule" "allow_all_egress" {
  security_group_id = aws_security_group.rds_security_group.id
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = -1 # Equivalent to all ports
}

resource "aws_db_instance" "rds_db" {
  allocated_storage           = 10
  db_name                     = "soundcloud_data_db"
  engine                      = "postgres"
  engine_version              = "16.15"
  instance_class              = "db.t4g.micro"
  manage_master_user_password = true
  username                    = "danieeeld2"
  db_subnet_group_name        = aws_db_subnet_group.rds_subnet_group.name
  vpc_security_group_ids      = [aws_security_group.rds_security_group.id]
  publicly_accessible         = true
  skip_final_snapshot         = true
}

# ============================================================
# Outputs
# ============================================================

output "rds_endpoint" {
  description = "The connection endpoint (host) for the RDS Postgres instance"
  value       = aws_db_instance.rds_db.address
}

output "rds_port" {
  description = "The port RDS Postgres is listening on"
  value       = aws_db_instance.rds_db.port
}

output "rds_secret_arn" {
  description = "ARN of the Secrets Manager secret holding the auto-generated master password"
  value       = aws_db_instance.rds_db.master_user_secret[0].secret_arn
}

output "lambda_role_arn" {
  description = "ARN of the Lambda execution role, needed when defining the Lambda module"
  value       = aws_iam_role.lambda_role.arn
}