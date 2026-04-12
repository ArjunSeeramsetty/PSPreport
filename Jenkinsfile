// Jenkinsfile.ci - Continuous Integration Pipeline
// This pipeline handles building and testing the Docker image
// It pushes the image to a local Docker registry at localhost:5000

pipeline {
    agent any

    environment {
        // Local Docker registry configuration
        // This assumes you have a local Docker registry running on port 5000
        // To set up the registry:
        // 1. docker pull registry:2
        // 2. docker run -d -p 5000:5000 --restart=always --name registry registry:2
        // 3. Add "insecure-registries": ["localhost:5000"] to /etc/docker/daemon.json
        DOCKER_REGISTRY = "localhost:5000"
        DOCKER_IMAGE_NAME = "psp-report-pipeline"
    }

    stages {
        stage('Verify Environment') {
            steps {
                // Verify Docker socket is accessible
                sh '''
                    if [ ! -S /var/run/docker.sock ]; then
                        echo "Docker socket not found at /var/run/docker.sock"
                        exit 1
                    fi
                    # Test Docker access
                    docker info
                '''
            }
        }

        stage('Checkout Code') {
            steps {
                // Using the credential ID that matches what you set up in Jenkins
                git branch: 'main',
                    credentialsId: 'Powerflow_AccessID',  // Make sure this matches the ID you created
                    url: 'https://github.com/ArjunSeeramsetty/PSPreport.git'  // Added .git extension
            }
        }

        stage('Build Docker Image') {
            steps {
                script {
                    def dockerImageTag = "${env.DOCKER_REGISTRY}/${env.DOCKER_IMAGE_NAME}:${env.BUILD_NUMBER}"

                    // Build the Docker image
                    sh """
                        docker build -t ${dockerImageTag} \\
                            --build-arg PYTHON_VERSION=3.8 \\
                            --build-arg AIRFLOW_VERSION=2.7.1 \\
                            --build-arg CHROME_VERSION=latest \\
                            .
                    """
                    echo "Docker image built: ${dockerImageTag}"
                    env.DOCKER_IMAGE_TAG = dockerImageTag
                }
            }
        }

        stage('Run Tests') {
            steps {
                script {
                    // Run DAG integrity tests
                    echo "Running DAG integrity tests..."
                    sh """
                        docker run --rm ${env.DOCKER_IMAGE_TAG} \\
                            python -c "from airflow.models import DagBag; \\
                            dag_bag = DagBag(); \\
                            assert not dag_bag.import_errors, f'DAG import errors: {dag_bag.import_errors}'"
                    """

                    // Run unit tests
                    echo "Running unit tests..."
                    sh """
                        docker run --rm ${env.DOCKER_IMAGE_TAG} \\
                            pytest tests/unit/ -v
                    """

                    // Run integration tests
                    echo "Running integration tests..."
                    sh """
                        docker run --rm ${env.DOCKER_IMAGE_TAG} \\
                            pytest tests/integration/ -v
                    """

                    // Run code quality checks
                    echo "Running code quality checks..."
                    sh """
                        docker run --rm ${env.DOCKER_IMAGE_TAG} \\
                            pylint dags/get_report_url.py dags/PDFparser_Gemini.py dags/Data_Insertion.py dags/pdf_pipeline_dag.py
                    """
                }
            }
        }

        stage('Push to Local Registry') {
            steps {
                script {
                    // Check if local registry is running, start if not
                    sh """
                        if ! docker ps | grep -q registry:2; then
                            echo "Starting local Docker registry..."
                            docker run -d -p 5000:5000 --restart=always --name registry registry:2
                        fi
                    """

                    // Push to local registry
                    sh """
                        docker push ${env.DOCKER_IMAGE_TAG}
                    """
                    echo "Docker image pushed to local registry: ${env.DOCKER_IMAGE_TAG}"

                    // Archive the build number and image tag for the CD pipeline
                    writeFile file: 'last_successful_build_info.txt', text: "BUILD_NUMBER=${env.BUILD_NUMBER}\nDOCKER_IMAGE_TAG=${env.DOCKER_IMAGE_TAG}"
                    archiveArtifacts artifacts: 'last_successful_build_info.txt', fingerprint: true
                }
            }
        }
    }

    post {
        always {
            sh """
                docker system prune -f --filter "until=24h" --filter "label!=local-registry"
                rm -rf .pytest_cache
                rm -rf __pycache__
            """
            echo "CI Pipeline finished."
        }
        success {
            echo "CI Pipeline completed successfully! Image ${env.DOCKER_IMAGE_TAG} pushed to local registry."
            // Trigger the CD pipeline after successful CI
            build job: 'PSP_Report_Pipeline_CD', parameters: [string(name: 'LAST_CI_BUILD_NUMBER', value: "${env.BUILD_NUMBER}")]
        }
        failure {
            echo "CI Pipeline failed. Check logs for details."
        }
        unstable {
            echo "CI Pipeline is unstable, some tests might have failed."
        }
    }
}