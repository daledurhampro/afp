# Terraform Infrastructure

This directory contains Terraform configurations for the AFP Financial Planner project.

## Structure

Each deployment stage has its own independent Terraform directory, deployed in numeric order:

- **`2_sagemaker/`** - SageMaker serverless endpoint for embeddings
- **`3_ingestion/`** - S3 Vectors, Lambda, and API Gateway for document ingestion
- **`4_researcher/`** - App Runner service for AI researcher agent
- **`5_database/`** - Aurora Serverless v2 PostgreSQL with Data API
- **`6_agents/`** - Lambda functions for agent orchestra
- **`7_frontend/`** - API Lambda and frontend infrastructure
- **`8_enterprise/`** - CloudWatch dashboards, monitoring and observability

## Key Design Decisions

### Why Separate Directories?

1. **Clarity**: Each deployment stage corresponds to exactly one Terraform directory
2. **Independent Deployment**: Each stage can be deployed without affecting the others
3. **Reduced Risk**: Mistakes in one stage don't impact previously deployed infrastructure
4. **Progressive Deploy**: Later stages are deployed only after the earlier ones they depend on

### Why Local State?

1. **Simplicity**: No need to set up and manage an S3 state bucket
2. **Zero Dependencies**: Can start deploying immediately without prerequisite infrastructure
3. **Cost Savings**: No S3 storage costs for state files
4. **Security**: State files are automatically gitignored

## Usage

For each deployment stage:

```bash
# Navigate to the stage's directory
cd terraform/2_sagemaker  # (or 3_ingestion, 4_researcher, etc.)

# Initialize Terraform (only needed once per directory)
terraform init

# Review what will be created
terraform plan

# Deploy the infrastructure
terraform apply

# When done with that stage (optional)
terraform destroy
```

## Environment Variables

Some Terraform configurations require environment variables from your `.env` file:

- `OPENAI_API_KEY` - For the researcher agent (`4_researcher`)
- `AFP_API_ENDPOINT` - API Gateway endpoint (output of `3_ingestion`)
- `AFP_API_KEY` - API key for ingestion (output of `3_ingestion`)
- `AURORA_CLUSTER_ARN` - Aurora cluster ARN (output of `5_database`)
- `AURORA_SECRET_ARN` - Secrets Manager ARN (output of `5_database`)
- `VECTOR_BUCKET` - S3 Vectors bucket name (output of `3_ingestion`)
- `BEDROCK_MODEL_ID` - Bedrock model to use (`6_agents`)

## State Management

- Each directory maintains its own `terraform.tfstate` file
- State files are stored locally (not in S3)
- All `*.tfstate` files are gitignored for security
- Back up state files before making major changes

## Production Considerations

This structure is optimized for dev and showcase projects. In production, you might consider:

- **Remote State**: Store state in S3 with state locking via DynamoDB
- **Modules**: Share common configurations across environments
- **Workspaces**: Manage multiple environments (dev, staging, prod)
- **CI/CD**: Automated deployment pipelines
- **Terragrunt**: Orchestrate multiple Terraform configurations

## Troubleshooting

If you encounter issues:

1. **State Conflicts**: Each directory has independent state. If you need to import existing resources:
   ```bash
   terraform import <resource_type>.<resource_name> <resource_id>
   ```

2. **Missing Dependencies**: Ensure you've deployed the earlier stages and have the required environment variables

3. **Clean Slate**: To start over in any directory:
   ```bash
   terraform destroy  # Remove resources
   rm -rf .terraform terraform.tfstate*  # Clean local files
   terraform init  # Reinitialize
   ```