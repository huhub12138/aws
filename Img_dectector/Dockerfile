FROM public.ecr.aws/lambda/python:3.10

# Set working directory
WORKDIR /var/task

# Copy code and model
COPY lambda.py ./
COPY model.pt ./
COPY requirements.txt ./

# Install dependencies
RUN pip install -r requirements.txt

# Lambda entrypoint
CMD ["lambda.handler"]
