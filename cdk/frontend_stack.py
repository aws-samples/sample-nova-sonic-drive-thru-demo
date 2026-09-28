# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Frontend stack: deploys the pre-built frontend (with runtime-config.json) to S3."""

import os
import aws_cdk as cdk
from aws_cdk import (
    Stack,
    aws_s3 as s3,
    aws_s3_deployment as s3deploy,
    aws_cloudfront as cloudfront,
)
from constructs import Construct


class FrontendStack(Stack):

    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        hosting_bucket_name: str,
        distribution_id: str,
        **kwargs,
    ) -> None:
        super().__init__(scope, construct_id, **kwargs)

        # Import existing resources from the backend stack
        hosting_bucket = s3.Bucket.from_bucket_name(
            self, "HostingBucket", hosting_bucket_name
        )
        distribution = cloudfront.Distribution.from_distribution_attributes(
            self, "Distribution",
            distribution_id=distribution_id,
            domain_name=f"{distribution_id}.cloudfront.net",
        )

        # Deploy the pre-built frontend dist/ (which includes runtime-config.json)
        frontend_dist_path = os.path.join(
            os.path.dirname(__file__), "..", "frontend", "dist"
        )

        # prune=False is required: this bucket is shared with the food images
        # deployed by BackendStack under the `images/` prefix. With CDK's default
        # prune=True, this deployment would delete every object not present in
        # frontend/dist — wiping those images on every frontend deploy.
        # Vite emits content-hashed asset filenames, so leftover old assets are
        # harmless; index.html and runtime-config.json are overwritten each time.
        s3deploy.BucketDeployment(
            self, "DeployFrontend",
            sources=[s3deploy.Source.asset(frontend_dist_path)],
            destination_bucket=hosting_bucket,
            distribution=distribution,
            distribution_paths=["/*"],
            prune=False,
        )
