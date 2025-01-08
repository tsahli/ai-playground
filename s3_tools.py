import io
import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional, Type, Union

import fitz  # PyMuPDF
import numpy as np
import pandas as pd
import pytesseract
from PIL import Image
from PyPDF2 import PdfReader

from tool import Tool


# Base operation class
class S3Operation(ABC):
    @abstractmethod
    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        pass

    @abstractmethod
    def get_parameters(self) -> Dict:
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        pass


# Operation implementations
class ListBucketsOperation(S3Operation):
    name = "list_buckets"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str] = None,
        key: Optional[str] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        response = s3_client.list_buckets()
        return {"buckets": [bucket["Name"] for bucket in response["Buckets"]]}

    def get_parameters(self) -> Dict:
        return {}


class ReadTextOperation(S3Operation):
    name = "read_text"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return {
            "content": response["Body"].read().decode("utf-8"),
            "content_type": response.get("ContentType"),
            "size": response.get("ContentLength"),
        }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
        }


class GetFileInfoOperation(S3Operation):
    name = "get_file_info"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        response = s3_client.get_object(Bucket=bucket, Key=key)
        return {
            "content_type": response.get("ContentType"),
            "size": response.get("ContentLength"),
            "last_modified": response.get("LastModified").isoformat(),
            "etag": response.get("ETag"),
        }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
        }


class AnalyzeCSVOperation(S3Operation):
    name = "analyze_csv"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        params = params or {}
        sample_size = params.get("sample_size")
        specific_columns = params.get("specific_columns")

        try:
            # Fetch file from S3
            response = s3_client.get_object(Bucket=bucket, Key=key)
            file_size = response.get("ContentLength", 0)

            # Read CSV into pandas
            df = pd.read_csv(
                io.BytesIO(response["Body"].read()),
                nrows=sample_size if sample_size else None,
            )

            # Filter columns if specified
            if specific_columns:
                df = df[specific_columns]

            # Basic file info
            basic_info = {
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "total_rows": len(df),
                "total_columns": len(df.columns),
                "columns": list(df.columns),
                "sample_size": sample_size if sample_size else len(df),
            }

            # Column analysis
            column_analysis = {}
            for column in df.columns:
                col_data = df[column]
                col_type = str(col_data.dtype)

                analysis = {
                    "dtype": col_type,
                    "null_count": int(col_data.isnull().sum()),
                    "null_percentage": round(
                        (col_data.isnull().sum() / len(df)) * 100, 2
                    ),
                    "unique_values": int(col_data.nunique()),
                }

                # Numeric column analysis
                if np.issubdtype(col_data.dtype, np.number):
                    analysis.update(
                        {
                            "min": (
                                float(col_data.min())
                                if not pd.isna(col_data.min())
                                else None
                            ),
                            "max": (
                                float(col_data.max())
                                if not pd.isna(col_data.max())
                                else None
                            ),
                            "mean": (
                                float(col_data.mean())
                                if not pd.isna(col_data.mean())
                                else None
                            ),
                            "median": (
                                float(col_data.median())
                                if not pd.isna(col_data.median())
                                else None
                            ),
                            "std": (
                                float(col_data.std())
                                if not pd.isna(col_data.std())
                                else None
                            ),
                            "zeros_count": int((col_data == 0).sum()),
                            "negative_count": int((col_data < 0).sum()),
                        }
                    )

                # String column analysis
                elif col_data.dtype == object:
                    # Get value counts for top 10 most common values
                    value_counts = col_data.value_counts().head(10).to_dict()
                    value_counts = {k: int(v) for k, v in value_counts.items()}

                    analysis.update(
                        {
                            "empty_string_count": int((col_data == "").sum()),
                            "whitespace_count": int(col_data.str.isspace().sum()),
                            "avg_length": float(col_data.str.len().mean()),
                            "top_values": value_counts,
                        }
                    )

                # Datetime analysis
                elif np.issubdtype(col_data.dtype, np.datetime64):
                    analysis.update(
                        {
                            "min_date": col_data.min().isoformat(),
                            "max_date": col_data.max().isoformat(),
                            "date_range_days": int(
                                (col_data.max() - col_data.min()).days
                            ),
                        }
                    )

                column_analysis[column] = analysis

            # Correlation analysis for numeric columns
            numeric_columns = df.select_dtypes(include=[np.number]).columns
            correlation_dict = {}
            if len(numeric_columns) > 1:
                correlation_matrix = df[numeric_columns].corr().round(3)
                correlation_dict = (
                    correlation_matrix.where(
                        np.triu(np.ones(correlation_matrix.shape), k=1).astype(bool)
                    )
                    .stack()
                    .to_dict()
                )
                correlation_dict = {
                    f"{k[0]}_{k[1]}": v
                    for k, v in correlation_dict.items()
                    if not pd.isna(v)
                }

            # Generate warnings
            warnings = []
            # Check for high null percentages
            for col, analysis in column_analysis.items():
                if analysis["null_percentage"] > 20:
                    warnings.append(
                        f"Column '{col}' has {analysis['null_percentage']}% null values"
                    )

            # Check for potential memory issues
            estimated_memory = (
                basic_info["total_rows"]
                * basic_info["total_columns"]
                * 8  # Assuming 8 bytes per cell on average
            ) / (
                1024 * 1024
            )  # Convert to MB

            if estimated_memory > 1000:  # More than 1GB
                warnings.append(
                    f"Large dataset detected. Estimated memory usage: {estimated_memory:.2f} MB"
                )

            # Check for high cardinality in string columns
            for col, analysis in column_analysis.items():
                if (
                    analysis.get("dtype") == "object"
                    and analysis["unique_values"] / basic_info["total_rows"] > 0.9
                ):
                    warnings.append(
                        f"Column '{col}' has high cardinality "
                        f"({analysis['unique_values']} unique values)"
                    )

            return {
                "basic_info": basic_info,
                "column_analysis": column_analysis,
                "correlations": correlation_dict,
                "analysis_timestamp": datetime.utcnow().isoformat(),
                "warnings": warnings,
            }

        except Exception as e:
            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
            "sample_size": {
                "type": "integer",
                "description": "Number of rows to sample (optional)",
            },
            "specific_columns": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of specific columns to analyze (optional)",
            },
        }


class PDFAnalyzeOperation(S3Operation):
    name = "analyze_pdf"

    def _safe_get_tables(self, page) -> int:
        """Safely get number of tables on a page"""
        try:
            tables = page.find_tables()
            if hasattr(tables, "__len__"):
                return len(tables)
            if hasattr(tables, "tables"):
                return len(tables.tables)
            return 0
        except Exception:
            return 0

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        try:
            # Fetch file from S3
            response = s3_client.get_object(Bucket=bucket, Key=key)
            file_content = response["Body"].read()
            file_size = response.get("ContentLength", 0)

            # Initialize PDF readers
            pdf_reader = PdfReader(io.BytesIO(file_content))
            doc = fitz.open(stream=file_content, filetype="pdf")

            # Basic document info
            basic_info = {
                "file_size_bytes": file_size,
                "file_size_mb": round(file_size / (1024 * 1024), 2),
                "total_pages": len(pdf_reader.pages),
                "is_encrypted": pdf_reader.is_encrypted,
                "metadata": {
                    "title": pdf_reader.metadata.get("/Title", ""),
                    "author": pdf_reader.metadata.get("/Author", ""),
                    "subject": pdf_reader.metadata.get("/Subject", ""),
                    "creator": pdf_reader.metadata.get("/Creator", ""),
                    "producer": pdf_reader.metadata.get("/Producer", ""),
                    "creation_date": pdf_reader.metadata.get("/CreationDate", ""),
                    "modification_date": pdf_reader.metadata.get("/ModDate", ""),
                },
            }

            # Page analysis
            pages_analysis = []
            total_extracted_words = 0
            total_images = 0
            total_tables = 0
            total_links = 0
            extracted_text = []

            for page_num in range(len(pdf_reader.pages)):
                page_analysis = {"page_number": page_num + 1}

                # Get text from both readers and use the one with more content
                pdf_text = pdf_reader.pages[page_num].extract_text()
                doc_text = doc[page_num].get_text()

                page_text = pdf_text if len(pdf_text) > len(doc_text) else doc_text
                total_extracted_words += len(page_text.split())
                extracted_text.append(page_text)

                page_analysis["text_length"] = len(page_text)
                page_analysis["text_preview"] = (
                    page_text[:200] + "..." if len(page_text) > 200 else page_text
                )

                # Get page elements
                doc_page = doc[page_num]
                images = len(doc_page.get_images())
                tables = self._safe_get_tables(doc_page)
                links = len(doc_page.get_links())

                page_analysis.update(
                    {"image_count": images, "table_count": tables, "link_count": links}
                )

                total_images += images
                total_tables += tables
                total_links += links

                pages_analysis.append(page_analysis)

            # Generate document statistics
            statistics = {
                "text_extraction": {
                    "total_pages_processed": len(pages_analysis),
                    "pages_with_content": sum(
                        1 for p in pages_analysis if p["text_length"] > 0
                    ),
                    "total_words": total_extracted_words,
                },
                "document_elements": {
                    "total_images": total_images,
                    "total_tables": total_tables,
                    "total_links": total_links,
                },
            }

            return {
                "basic_info": basic_info,
                "statistics": statistics,
                "pages_analysis": pages_analysis,
                "extracted_text": extracted_text,
                "analysis_timestamp": datetime.utcnow().isoformat(),
                "status": "success",
            }

        except Exception as e:
            import traceback

            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "stack_trace": traceback.format_exc(),
                "status": "error",
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
        }


class GeneratePresignedUrlOperation(S3Operation):
    name = "generate_presigned_url"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        try:
            if not bucket or not key:
                return {"error": "Both bucket and key are required"}

            params = params or {}
            expiration = params.get("expiration", 604800)  # Default 1 week
            http_method = params.get("http_method", "GET")

            # Generate the presigned URL
            url = s3_client.generate_presigned_url(
                ClientMethod=f"{http_method.lower()}_object",
                Params={
                    "Bucket": bucket,
                    "Key": key,
                },
                ExpiresIn=expiration,
                HttpMethod=http_method,
            )

            return {
                "status": "success",
                "url": url,
                "expires_in": expiration,
                "http_method": http_method,
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
            "params": {
                "type": "object",
                "properties": {
                    "expiration": {
                        "type": "integer",
                        "description": "URL expiration time in seconds (default: 604800 - one week)",
                    },
                    "http_method": {
                        "type": "string",
                        "enum": ["GET", "PUT"],
                        "description": "HTTP method for the URL (default: GET)",
                    },
                },
            },
        }


class WriteTextOperation(S3Operation):
    name = "write_text"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        try:
            if not params or "content" not in params:
                return {"error": "No content provided to save"}

            content = params["content"]
            content_type = params.get("content_type", "text/plain")

            if isinstance(content, str):
                content = content.encode("utf-8")

            response = s3_client.put_object(
                Bucket=bucket, Key=key, Body=content, ContentType=content_type
            )

            return {
                "status": "success",
                "etag": response.get("ETag"),
                "version_id": response.get("VersionId"),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except Exception as e:
            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
            "params": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": "string",
                        "description": "Text content to save",
                    },
                    "content_type": {
                        "type": "string",
                        "description": "Content type (MIME type) of the file (optional, defaults to text/plain)",
                    },
                },
                "required": ["content"],
            },
        }


class WriteJsonOperation(S3Operation):
    name = "write_json"

    def execute(
        self,
        s3_client: Any,
        bucket: Optional[str],
        key: Optional[str],
        params: Optional[Dict[str, Any]] = None,
    ) -> Dict:
        try:
            if not params or "content" not in params:
                return {"error": "No content provided to save"}

            content = params["content"]

            # Handle both dictionary/list input and string input
            if isinstance(content, (dict, list)):
                content = json.dumps(content, indent=params.get("indent", 2))
            elif not isinstance(content, str):
                return {
                    "error": "Content must be a JSON-serializable object or a JSON string"
                }

            # Encode the JSON string to bytes
            content = content.encode("utf-8")

            # Always use application/json content type for JSON files
            content_type = "application/json"

            response = s3_client.put_object(
                Bucket=bucket, Key=key, Body=content, ContentType=content_type
            )

            return {
                "status": "success",
                "etag": response.get("ETag"),
                "version_id": response.get("VersionId"),
                "timestamp": datetime.utcnow().isoformat(),
            }

        except json.JSONDecodeError as e:
            return {
                "error": f"Invalid JSON format: {str(e)}",
                "error_type": "JSONDecodeError",
                "timestamp": datetime.utcnow().isoformat(),
            }
        except Exception as e:
            return {
                "error": str(e),
                "error_type": type(e).__name__,
                "timestamp": datetime.utcnow().isoformat(),
            }

    def get_parameters(self) -> Dict:
        return {
            "bucket": {"type": "string", "description": "S3 bucket name"},
            "key": {"type": "string", "description": "S3 object key"},
            "params": {
                "type": "object",
                "properties": {
                    "content": {
                        "type": ["object", "array", "string"],
                        "description": "JSON content to save (can be a JSON-serializable object or a JSON string)",
                    },
                    "indent": {
                        "type": "integer",
                        "description": "Number of spaces for JSON indentation (optional, defaults to 2)",
                    },
                },
                "required": ["content"],
            },
        }


# Operation Registry
class OperationRegistry:
    def __init__(self):
        self._operations: Dict[str, Type[S3Operation]] = {}

    def register(self, operation_class: Type[S3Operation]):
        self._operations[operation_class.name] = operation_class

    def get_operation(self, name: str) -> Optional[S3Operation]:
        operation_class = self._operations.get(name)
        return operation_class() if operation_class else None

    def get_all_operations(self) -> List[str]:
        return list(self._operations.keys())

    def get_all_parameters(self) -> Dict:
        parameters = {}
        for op_name, op_class in self._operations.items():
            parameters[op_name] = op_class().get_parameters()
        return parameters


# Enhanced S3FileAnalyzer
class S3FileAnalyzer:
    def __init__(self, session):
        self.session = session
        self.s3 = session.client("s3")
        self.registry = OperationRegistry()

        # Register default operations
        self.registry.register(ListBucketsOperation)
        self.registry.register(ReadTextOperation)
        self.registry.register(GetFileInfoOperation)
        self.registry.register(AnalyzeCSVOperation)
        self.registry.register(PDFAnalyzeOperation)
        self.registry.register(WriteTextOperation)
        self.registry.register(WriteJsonOperation)
        self.registry.register(GeneratePresignedUrlOperation)

    def add_operation(self, operation_class: Type[S3Operation]):
        """Add a new operation type to the analyzer"""
        self.registry.register(operation_class)

    def create_tool(self) -> Tool:
        def analyze_s3_file(
            operation: str,
            bucket: Optional[str] = None,
            key: Optional[str] = None,
            params: Optional[Dict[str, Any]] = None,
        ) -> Dict:
            try:
                op = self.registry.get_operation(operation)
                if not op:
                    return {"error": f"Unknown operation: {operation}"}

                if operation != "list_buckets" and (not bucket or not key):
                    return {"error": "Bucket and key are required for this operation"}

                return op.execute(self.s3, bucket, key, params)

            except self.s3.exceptions.NoSuchKey:
                return {"error": f"File {key} not found in bucket {bucket}"}
            except self.s3.exceptions.NoSuchBucket:
                return {"error": f"Bucket {bucket} not found"}
            except Exception as e:
                return {"error": str(e)}

        # Build parameters schema dynamically
        operations = self.registry.get_all_operations()
        all_parameters = self.registry.get_all_parameters()

        parameters = {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": operations,
                    "description": "The operation to perform",
                },
                **{k: v for op in all_parameters.values() for k, v in op.items()},
            },
            "required": ["operation"],
        }

        return Tool(
            name="analyze_s3",
            description="Analyze files and buckets in S3. Supports various operations including CSV analysis.",
            parameters=parameters,
            function=analyze_s3_file,
        )
