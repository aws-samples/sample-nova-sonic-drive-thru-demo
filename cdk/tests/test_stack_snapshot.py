# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""CDK resource verification tests for BackendStack and FrontendStack.

Validates Requirements 7.1–7.11, plus regression tests for failures that only showed up
after deployment (each is invisible in local development):
- a CSP wildcard in the middle of a hostname silently blocked Cognito and the agent WebSocket
- the frontend deployment pruned the food images out of the shared hosting bucket
- CloudFront answered missing files with the app page and HTTP 200, hiding the missing images
- open sign-up let anyone open paid voice sessions
- the model ID in the agent and in its IAM grant drifted apart
"""

import json
import os
import re
import sys

import aws_cdk as cdk
import pytest
from aws_cdk.assertions import Match, Template

CDK_DIR = os.path.join(os.path.dirname(__file__), "..")
REPO_ROOT = os.path.join(CDK_DIR, "..")
sys.path.insert(0, CDK_DIR)  # the stacks
sys.path.insert(0, REPO_ROOT)  # smoke_test's CSP checker, so there is one implementation

from backend_stack import DEFAULT_BEDROCK_REGION, BackendStack  # noqa: E402
from frontend_stack import FrontendStack  # noqa: E402
from smoke_test import csp_problems  # noqa: E402

REGION = "us-east-1"
ENV = cdk.Environment(account="123456789012", region=REGION)


@pytest.fixture(scope="module")
def template():
    """Synthesize the backend stack in a concrete region so region-pinned values resolve."""
    return Template.from_stack(BackendStack(cdk.App(), "TestStack", env=ENV))


@pytest.fixture(scope="module")
def template_json(template):
    return template.to_json()


@pytest.fixture(scope="module")
def frontend_template():
    # Packages frontend/dist, so the frontend must be built first (CI does this)
    stack = FrontendStack(
        cdk.App(), "TestFrontendStack",
        hosting_bucket_name="test-hosting-bucket", distribution_id="E2EXAMPLE", env=ENV,
    )
    return Template.from_stack(stack)


def _resources(template_json, resource_type):
    return [r for r in template_json["Resources"].values() if r["Type"] == resource_type]


class TestOutputs:
    def test_outputs_used_by_deploy_scripts_exist(self, template_json):
        """deploy.sh, generate_config.py and smoke_test.py read these outputs."""
        expected = {
            "MenuTableName", "OrdersTableName", "ImagesBucketName", "HostingBucketName",
            "DistributionId", "DistributionDomainName", "UserPoolId", "UserPoolClientId",
            "AgentRuntimeId", "AgentRuntimeArn",
        }
        assert expected <= set(template_json["Outputs"])


class TestDynamoDBTables:
    """Requirements 7.1, 7.2."""

    def test_has_two_dynamodb_tables(self, template):
        template.resource_count_is("AWS::DynamoDB::Table", 2)

    def test_menu_table_schema(self, template):
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "TableName": "DriveThruMenu",
            "KeySchema": Match.array_with([
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ]),
        })

    def test_orders_table_schema(self, template):
        template.has_resource_properties("AWS::DynamoDB::Table", {
            "TableName": "DriveThruOrders",
            "KeySchema": Match.array_with([{"AttributeName": "orderId", "KeyType": "HASH"}]),
        })

    def test_tables_use_pay_per_request(self, template):
        template.has_resource_properties("AWS::DynamoDB::Table", {"BillingMode": "PAY_PER_REQUEST"})


class TestS3Buckets:
    """Requirements 7.3, 7.4."""

    def test_bucket_count(self, template):
        template.resource_count_is("AWS::S3::Bucket", 4)

    def test_buckets_block_public_access(self, template):
        template.has_resource_properties("AWS::S3::Bucket", {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True, "BlockPublicPolicy": True,
                "IgnorePublicAcls": True, "RestrictPublicBuckets": True,
            },
        })


class TestCloudFront:
    """Requirements 7.5, 7.11."""

    def test_has_one_distribution(self, template):
        template.resource_count_is("AWS::CloudFront::Distribution", 1)

    def test_has_origin_access_identity(self, template):
        template.resource_count_is("AWS::CloudFront::CloudFrontOriginAccessIdentity", 1)

    def test_distribution_has_default_root_object(self, template):
        template.has_resource_properties("AWS::CloudFront::Distribution", {
            "DistributionConfig": Match.object_like({"DefaultRootObject": "index.html"}),
        })

    def test_distribution_redirects_to_https(self, template):
        template.has_resource_properties("AWS::CloudFront::Distribution", {
            "DistributionConfig": Match.object_like({
                "DefaultCacheBehavior": Match.object_like({"ViewerProtocolPolicy": "redirect-to-https"}),
            }),
        })

    def test_csp_is_valid_and_allows_the_endpoints_the_app_uses(self, template_json):
        [policy] = _resources(template_json, "AWS::CloudFront::ResponseHeadersPolicy")
        csp = policy["Properties"]["ResponseHeadersPolicyConfig"]["SecurityHeadersConfig"][
            "ContentSecurityPolicy"]["ContentSecurityPolicy"]
        assert isinstance(csp, str), "CSP should resolve to a literal string in a concrete region"
        assert csp_problems(csp, [
            f"https://cognito-idp.{REGION}.amazonaws.com",
            f"wss://bedrock-agentcore.{REGION}.amazonaws.com",
        ]) == []

    def test_csp_checker_rejects_mid_hostname_wildcards(self):
        """The header that broke production must fail this suite."""
        broken = ("connect-src 'self' https://cognito-idp.*.amazonaws.com "
                  "wss://bedrock-agentcore.*.amazonaws.com")
        problems = csp_problems(broken, [f"wss://bedrock-agentcore.{REGION}.amazonaws.com"])
        assert any("invalid source" in p for p in problems)
        assert any("blocks wss://" in p for p in problems)

    def test_missing_files_are_not_served_as_the_app_page(self, template_json):
        """The app has no client-side routes. Mapping 403/404 to index.html with a 200 only
        disguised the missing images as successful responses."""
        [distribution] = _resources(template_json, "AWS::CloudFront::Distribution")
        error_responses = distribution["Properties"]["DistributionConfig"].get("CustomErrorResponses", [])
        assert [e for e in error_responses if e.get("ResponseCode") == 200] == []


class TestCognito:
    """Requirements 7.6, 7.7."""

    def test_has_one_user_pool_and_client(self, template):
        template.resource_count_is("AWS::Cognito::UserPool", 1)
        template.resource_count_is("AWS::Cognito::UserPoolClient", 1)

    def test_user_pool_has_email_sign_in(self, template):
        template.has_resource_properties("AWS::Cognito::UserPool", {
            "UsernameAttributes": Match.array_with(["email"]),
        })

    def test_only_admins_can_create_accounts(self, template):
        """Every account can open paid Nova Sonic sessions, so self sign-up stays off."""
        template.has_resource_properties("AWS::Cognito::UserPool", {
            "AdminCreateUserConfig": Match.object_like({"AllowAdminCreateUserOnly": True}),
        })


class TestAgentRuntime:
    """Requirement 7.9."""

    def test_runtime_role_is_assumed_by_agentcore(self, template):
        template.has_resource_properties("AWS::IAM::Role", {
            "AssumeRolePolicyDocument": Match.object_like({
                "Statement": Match.array_with([
                    Match.object_like({
                        "Principal": Match.object_like({"Service": "bedrock-agentcore.amazonaws.com"}),
                    }),
                ]),
            }),
        })

    def test_runtime_may_invoke_the_model_the_agent_uses(self, template, template_json):
        """The model ID lives in agent/main.py and in the IAM grant; they must agree, and the
        grant must be in the region the agent is told to call the model in."""
        with open(os.path.join(REPO_ROOT, "agent", "main.py")) as f:
            [model_id] = re.findall(r'model_id="([^"]+)"', f.read())
        template.has_resource_properties("AWS::BedrockAgentCore::Runtime", {
            "EnvironmentVariables": Match.object_like({"BEDROCK_REGION": DEFAULT_BEDROCK_REGION}),
        })
        assert (f"arn:aws:bedrock:{DEFAULT_BEDROCK_REGION}::foundation-model/{model_id}"
                in json.dumps(template_json))


class TestFrontendStack:
    def test_frontend_deploy_does_not_prune_the_food_images(self, frontend_template):
        """The hosting bucket is shared with the images BackendStack uploads under images/."""
        frontend_template.has_resource_properties("Custom::CDKBucketDeployment", {"Prune": False})
