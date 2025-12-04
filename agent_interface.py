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
        pr_number = request.pr_number
        log.info(f"Received ReviewPR request: {repo_url} PR #{pr_number}")
        
        try:
            # The orchestrator is async, but gRPC handlers are sync by default unless using grpc-asyncio
            # For simplicity, we can run the async orchestrator in a new event loop or use asyncio.run
            # However, since we might be serving multiple requests, it's better to use the async gRPC server
            # But standard grpcio is sync. Let's use asyncio.run for now as the orchestrator does heavy lifting in Ray.
            
            review_comment = asyncio.run(self.orchestrator.review_pr(repo_url, pr_number))
            return agent_pb2.ReviewResponse(status="ok", review_comment=review_comment)
        except Exception as e:
            log.exception("Error during review")
            return agent_pb2.ReviewResponse(status="error", review_comment=str(e))

def serve():
    port = os.getenv("PORT", "50051")
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    agent_pb2_grpc.add_CodeReviewAgentServicer_to_server(CodeReviewAgentServicer(), server)
    server.add_insecure_port(f'[::]:{port}')
    log.info(f"Starting gRPC server on port {port}")
    server.start()
    server.wait_for_termination()

if __name__ == '__main__':
    serve()
