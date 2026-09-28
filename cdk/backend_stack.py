# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Backend stack: DynamoDB, S3, CloudFront, Cognito, AgentCore Runtime, seed data."""

import json
import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    RemovalPolicy,
    aws_dynamodb as dynamodb,
    aws_lambda as lambda_,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
    aws_cloudfront_origins as origins,
    aws_cognito as cognito,
    aws_iam as iam,
    aws_wafv2 as wafv2,
    custom_resources as cr,
)
import aws_cdk.aws_bedrock_agentcore_alpha as agentcore
from cdk_nag import NagSuppressions
from constructs import Construct


class BackendStack(Stack):

    def __init__(self, scope: Construct, construct_id: str, **kwargs) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # --- DynamoDB Tables ---

        self.menu_table = dynamodb.Table(
            self, "DriveThruMenu",
            table_name="DriveThruMenu",
            partition_key=dynamodb.Attribute(name="PK", type=dynamodb.AttributeType.STRING),
            sort_key=dynamodb.Attribute(name="SK", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.orders_table = dynamodb.Table(
            self, "DriveThruOrders",
            table_name="DriveThruOrders",
            partition_key=dynamodb.Attribute(name="orderId", type=dynamodb.AttributeType.STRING),
            billing_mode=dynamodb.BillingMode.PAY_PER_REQUEST,
            point_in_time_recovery_specification=dynamodb.PointInTimeRecoverySpecification(
                point_in_time_recovery_enabled=True,
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        # --- S3 Buckets ---

        # Access logs bucket for S3 server access logging
        self.access_logs_bucket = s3.Bucket(
            self, "AccessLogsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
        )

        self.images_bucket = s3.Bucket(
            self, "FoodImagesBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            server_access_logs_bucket=self.access_logs_bucket,
            server_access_logs_prefix="food-images-logs/",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        self.hosting_bucket = s3.Bucket(
            self, "FrontendHostingBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            server_access_logs_bucket=self.access_logs_bucket,
            server_access_logs_prefix="hosting-logs/",
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
        )

        # --- Seed Menu Data ---

        data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
        seed_lambda_path = os.path.join(os.path.dirname(__file__), "seed_lambda")
        menu_json_src = os.path.join(data_dir, "menu_items.json")

        with open(menu_json_src) as f:
            menu_data = json.load(f)

        # Build a temp directory with Lambda code + menu data for bundling
        import tempfile
        import shutil
        bundle_dir = tempfile.mkdtemp()
        # Copy Lambda handler
        shutil.copy2(os.path.join(seed_lambda_path, "index.py"), os.path.join(bundle_dir, "index.py"))
        # Copy menu data from single source of truth
        shutil.copy2(menu_json_src, os.path.join(bundle_dir, "menu_items.json"))

        seed_fn = lambda_.Function(
            self, "SeedMenuFunction",
            runtime=lambda_.Runtime.PYTHON_3_13,
            handler="index.handler",
            code=lambda_.Code.from_asset(bundle_dir),
            timeout=cdk.Duration.minutes(2),
            environment={"TABLE_NAME": self.menu_table.table_name},
        )
        self.menu_table.grant_write_data(seed_fn)

        seed_provider = cr.Provider(self, "SeedMenuProvider", on_event_handler=seed_fn)
        cdk.CustomResource(
            self, "SeedMenuData",
            service_token=seed_provider.service_token,
            properties={"DataHash": str(hash(json.dumps(menu_data)))},
        )

        # --- Upload Food Images ---
        # Deploy to the hosting bucket so images are served via CloudFront
        # at relative paths like /images/classic-burger.svg
        images_dir = os.path.join(data_dir, "images")
        if os.path.isdir(images_dir):
            s3deploy.BucketDeployment(
                self, "DeployFoodImages",
                sources=[s3deploy.Source.asset(images_dir)],
                destination_bucket=self.hosting_bucket,
                destination_key_prefix="images",
                prune=False,
                memory_limit=512,
            )

        # --- WAF WebACL for CloudFront ---

        self.web_acl = wafv2.CfnWebACL(
            self, "CloudFrontWebACL",
            default_action=wafv2.CfnWebACL.DefaultActionProperty(allow={}),
            scope="CLOUDFRONT",
            visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                cloud_watch_metrics_enabled=True,
                metric_name="DriveThruWAFMetrics",
                sampled_requests_enabled=True,
            ),
            rules=[
                # AWS Managed Rules — Common Rule Set (OWASP Top 10)
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesCommonRuleSet",
                    priority=1,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesCommonRuleSet",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSCommonRules",
                        sampled_requests_enabled=True,
                    ),
                ),
                # AWS Managed Rules — Known Bad Inputs
                wafv2.CfnWebACL.RuleProperty(
                    name="AWSManagedRulesKnownBadInputsRuleSet",
                    priority=2,
                    override_action=wafv2.CfnWebACL.OverrideActionProperty(none={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        managed_rule_group_statement=wafv2.CfnWebACL.ManagedRuleGroupStatementProperty(
                            vendor_name="AWS",
                            name="AWSManagedRulesKnownBadInputsRuleSet",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="AWSKnownBadInputs",
                        sampled_requests_enabled=True,
                    ),
                ),
                # Rate-based rule — limit to 2000 requests per 5 minutes per IP
                wafv2.CfnWebACL.RuleProperty(
                    name="RateLimitRule",
                    priority=3,
                    action=wafv2.CfnWebACL.RuleActionProperty(block={}),
                    statement=wafv2.CfnWebACL.StatementProperty(
                        rate_based_statement=wafv2.CfnWebACL.RateBasedStatementProperty(
                            limit=2000,
                            aggregate_key_type="IP",
                        ),
                    ),
                    visibility_config=wafv2.CfnWebACL.VisibilityConfigProperty(
                        cloud_watch_metrics_enabled=True,
                        metric_name="RateLimitRule",
                        sampled_requests_enabled=True,
                    ),
                ),
            ],
        )

        # --- CloudFront Distribution ---

        # S3 bucket for CloudFront access logs
        self.cf_logs_bucket = s3.Bucket(
            self, "CloudFrontLogsBucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            enforce_ssl=True,
            removal_policy=RemovalPolicy.DESTROY,
            auto_delete_objects=True,
            object_ownership=s3.ObjectOwnership.OBJECT_WRITER,
        )

        self.oai = cloudfront.OriginAccessIdentity(
            self, "HostingOAI",
            comment="OAI for Drive-Thru frontend hosting bucket",
        )
        self.hosting_bucket.grant_read(self.oai)

        # --- Security Response Headers ---
        self.security_headers = cloudfront.ResponseHeadersPolicy(
            self, "SecurityHeadersPolicy",
            response_headers_policy_name="DriveThruSecurityHeaders",
            security_headers_behavior=cloudfront.ResponseSecurityHeadersBehavior(
                content_security_policy=cloudfront.ResponseHeadersContentSecurityPolicy(
                    # Allow scripts/styles from self and inline (needed for Vite builds).
                    # connect-src allows Cognito and AgentCore WebSocket endpoints.
                    content_security_policy=(
                        "default-src 'self'; "
                        "script-src 'self'; "
                        "style-src 'self' 'unsafe-inline'; "
                        "img-src 'self' data:; "
                        "font-src 'self'; "
                        "connect-src 'self' https://cognito-idp.*.amazonaws.com https://*.auth.*.amazoncognito.com wss://bedrock-agentcore.*.amazonaws.com; "
                        "media-src 'self' blob:; "
                        "frame-ancestors 'none'; "
                        "base-uri 'self'; "
                        "form-action 'self';"
                    ),
                    override=True,
                ),
                content_type_options=cloudfront.ResponseHeadersContentTypeOptions(override=True),
                frame_options=cloudfront.ResponseHeadersFrameOptions(
                    frame_option=cloudfront.HeadersFrameOption.DENY,
                    override=True,
                ),
                referrer_policy=cloudfront.ResponseHeadersReferrerPolicy(
                    referrer_policy=cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN,
                    override=True,
                ),
                strict_transport_security=cloudfront.ResponseHeadersStrictTransportSecurity(
                    access_control_max_age=cdk.Duration.days(365),
                    include_subdomains=True,
                    preload=True,
                    override=True,
                ),
                xss_protection=cloudfront.ResponseHeadersXSSProtection(
                    protection=True,
                    mode_block=True,
                    override=True,
                ),
            ),
        )

        self.distribution = cloudfront.Distribution(
            self, "FrontendDistribution",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.S3BucketOrigin.with_origin_access_identity(
                    self.hosting_bucket, origin_access_identity=self.oai,
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                response_headers_policy=self.security_headers,
            ),
            default_root_object="index.html",
            minimum_protocol_version=cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
            web_acl_id=self.web_acl.attr_arn,
            enable_logging=True,
            log_bucket=self.cf_logs_bucket,
            log_file_prefix="cf-access-logs/",
            error_responses=[
                cloudfront.ErrorResponse(http_status=403, response_http_status=200, response_page_path="/index.html"),
                cloudfront.ErrorResponse(http_status=404, response_http_status=200, response_page_path="/index.html"),
            ],
        )

        # --- Cognito ---

        self.user_pool = cognito.UserPool(
            self, "DriveThruUserPool",
            user_pool_name="DriveThruUserPool",
            self_sign_up_enabled=True,
            sign_in_aliases=cognito.SignInAliases(email=True),
            auto_verify=cognito.AutoVerifiedAttrs(email=True),
            standard_attributes=cognito.StandardAttributes(
                email=cognito.StandardAttribute(required=True, mutable=True),
            ),
            password_policy=cognito.PasswordPolicy(
                min_length=8, require_lowercase=True, require_uppercase=True,
                require_digits=True, require_symbols=True,
            ),
            feature_plan=cognito.FeaturePlan.PLUS,
            standard_threat_protection_mode=cognito.StandardThreatProtectionMode.FULL_FUNCTION,
            removal_policy=RemovalPolicy.DESTROY,
        )

        self.user_pool_client = self.user_pool.add_client(
            "DriveThruUserPoolClient",
            user_pool_client_name="DriveThruWebClient",
            auth_flows=cognito.AuthFlow(user_password=True, user_srp=True),
            generate_secret=False,
            id_token_validity=cdk.Duration.minutes(15),
            access_token_validity=cdk.Duration.minutes(15),
        )

        # --- AgentCore Runtime ---

        # Build the agent Docker image and deploy to AgentCore Runtime.
        # The Dockerfile installs all Python dependencies (strands-agents, boto3, etc.)
        agent_code_path = os.path.join(os.path.dirname(__file__), "..", "agent")

        self.agent_runtime = agentcore.Runtime(
            self, "DriveThruAgentRuntimeV4",
            runtime_name="DriveThruVoiceAgentV4",
            agent_runtime_artifact=agentcore.AgentRuntimeArtifact.from_asset(agent_code_path),
            authorizer_configuration=agentcore.RuntimeAuthorizerConfiguration.using_cognito(
                self.user_pool, [self.user_pool_client],
            ),
            environment_variables={
                "MENU_TABLE_NAME": self.menu_table.table_name,
                "ORDERS_TABLE_NAME": self.orders_table.table_name,
                "IMAGES_BUCKET_NAME": self.images_bucket.bucket_name,
                "AWS_REGION": self.region,
            },
            description="Drive-thru voice ordering agent powered by Nova Sonic",
        )

        self.agent_runtime.role.add_to_policy(iam.PolicyStatement(
            effect=iam.Effect.ALLOW,
            actions=["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
            resources=[
                f"arn:aws:bedrock:us-east-1:{self.account}:inference-profile/us.amazon.nova-2-sonic-v1:0",
                "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-2-sonic-v1:0",
            ],
        ))
        self.orders_table.grant_read_write_data(self.agent_runtime)
        self.menu_table.grant_read_data(self.agent_runtime)
        self.images_bucket.grant_read(self.agent_runtime)

        # --- Outputs ---

        cdk.CfnOutput(self, "MenuTableName", value=self.menu_table.table_name)
        cdk.CfnOutput(self, "OrdersTableName", value=self.orders_table.table_name)
        cdk.CfnOutput(self, "ImagesBucketName", value=self.images_bucket.bucket_name)
        cdk.CfnOutput(self, "HostingBucketName", value=self.hosting_bucket.bucket_name)
        cdk.CfnOutput(self, "DistributionId", value=self.distribution.distribution_id)
        cdk.CfnOutput(self, "DistributionDomainName", value=self.distribution.distribution_domain_name)
        cdk.CfnOutput(self, "UserPoolId", value=self.user_pool.user_pool_id)
        cdk.CfnOutput(self, "UserPoolClientId", value=self.user_pool_client.user_pool_client_id)
        cdk.CfnOutput(self, "AgentRuntimeId", value=self.agent_runtime.agent_runtime_id)
        cdk.CfnOutput(self, "AgentRuntimeArn", value=self.agent_runtime.agent_runtime_arn)

        # --- CDK Nag Suppressions ---

        # Access logs bucket does not need its own access logs (would be recursive)
        NagSuppressions.add_resource_suppressions(
            self.access_logs_bucket,
            [{"id": "AwsSolutions-S1", "reason": "This is the access logs bucket itself; enabling logging would create a recursive loop."}],
        )

        # CloudFront logs bucket does not need its own access logs
        NagSuppressions.add_resource_suppressions(
            self.cf_logs_bucket,
            [{"id": "AwsSolutions-S1", "reason": "This is the CloudFront logs bucket itself; enabling logging would create a recursive loop."}],
        )

        # CloudFront OAI vs OAC — OAI is used intentionally with S3BucketOrigin.with_origin_access_identity
        NagSuppressions.add_resource_suppressions(
            self.distribution,
            [
                {"id": "AwsSolutions-CFR1", "reason": "Geo restrictions not required for this demo application."},
                {"id": "AwsSolutions-CFR7", "reason": "Using OAI with S3BucketOrigin; OAC migration is planned but OAI still provides secure S3 access."},
                {"id": "AwsSolutions-CFR4", "reason": "Distribution uses the default CloudFront viewer certificate which enforces TLSv1 minimum. A custom domain with ACM certificate is required to enforce TLSv1.2; not applicable for this demo."},
            ],
        )

        # Cognito — MFA is not required for this demo (advanced security is enabled)
        NagSuppressions.add_resource_suppressions(
            self.user_pool,
            [
                {"id": "AwsSolutions-COG2", "reason": "MFA not required for this demo application. Enable for production."},
            ],
        )

        # Lambda runtime version — CDK BucketDeployment and custom resource provider use their own runtimes
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-L1",
                    "reason": "Lambda runtime versions for CDK-managed BucketDeployment and custom resource provider are controlled by the CDK framework.",
                },
            ],
        )

        # IAM managed policies — AWSLambdaBasicExecutionRole is standard for Lambda logging
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM4",
                    "reason": "AWSLambdaBasicExecutionRole is the standard managed policy for Lambda CloudWatch Logs access.",
                    "applies_to": [
                        "Policy::arn:<AWS::Partition>:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole",
                    ],
                },
            ],
        )

        # IAM wildcard permissions — CDK-managed constructs (BucketDeployment, custom resources, AgentCore)
        NagSuppressions.add_stack_suppressions(
            self,
            [
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Wildcard permissions are required by CDK BucketDeployment for S3 operations on deployment assets and destination bucket.",
                    "applies_to": [
                        "Action::s3:GetObject*",
                        "Action::s3:GetBucket*",
                        "Action::s3:List*",
                        "Action::s3:DeleteObject*",
                        "Action::s3:Abort*",
                        "Resource::arn:<AWS::Partition>:s3:::cdk-hnb659fds-assets-<AWS::AccountId>-<AWS::Region>/*",
                        "Resource::<FrontendHostingBucket12B6CA59.Arn>/*",
                        "Resource::<FoodImagesBucket01218028.Arn>/*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "Wildcard on Lambda function ARN version is required by the CDK custom resource provider framework to invoke the seed function.",
                    "applies_to": [
                        "Resource::<SeedMenuFunction60786485.Arn>:*",
                    ],
                },
                {
                    "id": "AwsSolutions-IAM5",
                    "reason": "AgentCore Runtime requires wildcard log group and workload identity permissions for its managed infrastructure.",
                    "applies_to": [
                        "Resource::arn:<AWS::Partition>:logs:<AWS::Region>:<AWS::AccountId>:log-group:/aws/bedrock-agentcore/runtimes/*",
                        "Resource::arn:<AWS::Partition>:logs:<AWS::Region>:<AWS::AccountId>:log-group:*",
                        "Resource::arn:<AWS::Partition>:logs:<AWS::Region>:<AWS::AccountId>:log-group:/aws/bedrock-agentcore/runtimes/*:log-stream:*",
                        "Resource::arn:<AWS::Partition>:bedrock-agentcore:<AWS::Region>:<AWS::AccountId>:workload-identity-directory/default/workload-identity/*",
                        "Resource::*",
                    ],
                },
            ],
        )
