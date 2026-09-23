terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.65"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }

  # Remote state is intentionally NOT configured. Local state is fine for this optional,
  # educational deployment; never commit *.tfstate (see .gitignore).
}
