import grpc
import protos.agent_pb2 as agent_pb2
import protos.agent_pb2_grpc as agent_pb2_grpc
import logging as log

log.basicConfig(level=log.INFO)

def run():
    with grpc.insecure_channel('localhost:50051') as channel:
        stub = agent_pb2_grpc.CodeReviewAgentStub(channel)
        log.info("Sending ReviewPR request...")
        response = stub.ReviewPR(agent_pb2.ReviewRequest(
            repo_url="https://github.com/huggingface/accelerate",
            pr_number=3321
        ))
        log.info("Review received: " + response.status)
        log.info(response.review_comment)

if __name__ == '__main__':
    run()
