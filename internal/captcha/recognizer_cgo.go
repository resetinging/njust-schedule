//go:build cgo

package captcha

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"image"
	_ "image/jpeg"
	_ "image/png"
	"strings"
	"sync"

	"github.com/disintegration/imaging"
	ort "github.com/yalue/onnxruntime_go"
)

// Solver lazily loads a single ONNX session. The model is over ten megabytes,
// so startup and cached-session logins must not pay that cost.
type Solver struct {
	modelPath   string
	runtimePath string

	mu          sync.Mutex
	session     *ort.DynamicAdvancedSession
	initErr     error
	initialized bool
}

func NewSolver(modelPath, runtimePath string) *Solver {
	return &Solver{
		modelPath:   strings.TrimSpace(modelPath),
		runtimePath: strings.TrimSpace(runtimePath),
	}
}

func (s *Solver) Solve(ctx context.Context, raw []byte) (string, error) {
	if s == nil {
		return "", ErrUnavailable
	}
	if err := ctx.Err(); err != nil {
		return "", err
	}
	if len(raw) == 0 || len(raw) > maxImageBytes {
		return "", fmt.Errorf("验证码图片大小无效")
	}
	config, _, err := image.DecodeConfig(bytes.NewReader(raw))
	if err != nil {
		return "", fmt.Errorf("解析验证码图片信息: %w", err)
	}
	if config.Width <= 0 || config.Height <= 0 ||
		config.Width > maxImageWidth || config.Height > maxImageHeight {
		return "", errors.New("验证码图片尺寸无效")
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	if err := s.ensureSessionLocked(); err != nil {
		return "", err
	}
	if err := ctx.Err(); err != nil {
		return "", err
	}

	img, _, err := image.Decode(bytes.NewReader(raw))
	if err != nil {
		return "", fmt.Errorf("解析验证码图片: %w", err)
	}
	height := img.Bounds().Dy()
	if height <= 0 {
		return "", errors.New("验证码图片尺寸无效")
	}
	width := img.Bounds().Dx() * modelHeight / height
	if width <= 0 {
		return "", errors.New("验证码图片尺寸无效")
	}
	resized := imaging.Resize(img, width, modelHeight, imaging.Lanczos)
	inputTensor, err := ort.NewTensor(
		ort.NewShape(1, 1, modelHeight, int64(width)),
		preprocess(resized, width),
	)
	if err != nil {
		return "", fmt.Errorf("创建验证码输入张量: %w", err)
	}
	defer inputTensor.Destroy()

	outputs := []ort.Value{nil}
	if err := s.session.Run([]ort.Value{inputTensor}, outputs); err != nil {
		return "", fmt.Errorf("验证码推理失败: %w", err)
	}
	var text string
	switch outputTensor := outputs[0].(type) {
	case *ort.Tensor[int64]:
		defer outputTensor.Destroy()
		text = decode(outputTensor.GetData())
	case *ort.Tensor[float32]:
		defer outputTensor.Destroy()
		text = decodeScores(outputTensor.GetData(), len(charset))
	default:
		if outputs[0] != nil {
			defer outputs[0].Destroy()
		}
		return "", fmt.Errorf("验证码输出类型异常: %T", outputs[0])
	}
	if err := ctx.Err(); err != nil {
		return "", err
	}

	text = strings.TrimSpace(text)
	if text == "" {
		return "", errors.New("验证码识别结果为空")
	}
	return text, nil
}

func (s *Solver) ensureSessionLocked() error {
	if s.initialized {
		if s.initErr != nil {
			return s.initErr
		}
		return nil
	}
	s.initialized = true
	s.initErr = nil
	if s.modelPath == "" {
		s.initErr = fmt.Errorf("%w: 未配置模型路径", ErrUnavailable)
		return s.initErr
	}
	if !ort.IsInitialized() {
		if s.runtimePath != "" {
			ort.SetSharedLibraryPath(s.runtimePath)
		}
		if err := ort.InitializeEnvironment(); err != nil {
			s.initErr = fmt.Errorf("%w: 初始化 ONNX Runtime 失败: %v", ErrUnavailable, err)
			return s.initErr
		}
	}
	options, err := ort.NewSessionOptions()
	if err != nil {
		s.initErr = fmt.Errorf("%w: 创建会话选项失败: %v", ErrUnavailable, err)
		return s.initErr
	}
	defer options.Destroy()
	if err := options.SetIntraOpNumThreads(1); err != nil {
		s.initErr = fmt.Errorf("%w: 设置推理线程失败: %v", ErrUnavailable, err)
		return s.initErr
	}
	if err := options.SetInterOpNumThreads(1); err != nil {
		s.initErr = fmt.Errorf("%w: 设置推理线程失败: %v", ErrUnavailable, err)
		return s.initErr
	}
	session, err := ort.NewDynamicAdvancedSession(
		s.modelPath,
		[]string{"input1"},
		[]string{"387"},
		options,
	)
	if err != nil {
		s.initErr = fmt.Errorf("%w: 加载验证码模型失败: %v", ErrUnavailable, err)
		return s.initErr
	}
	s.session = session
	return nil
}

func (s *Solver) Close() error {
	if s == nil {
		return nil
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.session == nil {
		return nil
	}
	err := s.session.Destroy()
	s.session = nil
	s.initialized = false
	s.initErr = nil
	return err
}
