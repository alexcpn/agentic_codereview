import grpc
from concurrent import futures
import logging as log
import os
import asyncio
import protos.agent_pb2 as agent_pb2
import protos.agent_pb2_grpc as agent_pb2_grpc
from review_orchestrator import CodeReviewOrchestrator
from load_dotenv import load_dotenv
load_dotenv()

# Configure logging
log.basicConfig(level=log.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

class CodeReviewAgentServicer(agent_pb2_grpc.CodeReviewAgentServicer):
    def __init__(self):
        self.orchestrator = CodeReviewOrchestrator()

    def ReviewPR(self, request, context):
        repo_url = request.repo_url
    async def ReviewPR(self, request, context):
        log.info(f"Received review request for PR #{request.pr_number}")
        try:
            async for result in self.orchestrator.review_pr_stream(request.repo_url, request.pr_number):
                yield agent_pb2.ReviewResponse(
                    status="Success",
                    review_comment=result["comment"],
                    file_path=result["file_path"]
                )
        except Exception as e:
            log.error(f"Error during review: {e}")
            yield agent_pb2.ReviewResponse(
                status="Error",
                review_comment=str(e),
                file_path=""
            )

async def serve():
    server = grpc.aio.server()
    agent_pb2_grpc.add_CodeReviewAgentServicer_to_server(CodeReviewAgentServicer(), server)
    server.add_insecure_port('[::]:50051')
    log.info("Starting Async gRPC server on port 50051...")
    await server.start()
    await server.wait_for_termination()

if __name__ == '__main__':
    import asyncio
    asyncio.run(serve())
