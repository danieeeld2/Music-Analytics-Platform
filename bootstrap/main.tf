terraform {
  required_version = ">= 1.5"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }
}

provider "aws" {
  region = "eu-west-1"
}

resource "aws_s3_bucket" "tfstate_bucket" {
  bucket = "music-analytics-tfstate"
}

resource "aws_s3_bucket_versioning" "tfstate_versioning" {
  bucket = aws_s3_bucket.tfstate_bucket.id
  versioning_configuration {
    status = "Enabled" # Allow bucket versioning for recovery
  }
}

resource "aws_s3_bucket_public_access_block" "tfstate_access_block" {
  bucket = aws_s3_bucket.tfstate_bucket.id

  # Denny Public Access
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_dynamodb_table" "tfstate_dynamodb_table" {
  name         = "dynamo-table-music-analytics-tfstate"
  hash_key     = "LockID"
  billing_mode = "PAY_PER_REQUEST" # See ADR 06

  attribute {
    name = "LockID"
    type = "S"
  }
}   